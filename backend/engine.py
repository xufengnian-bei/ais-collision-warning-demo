import asyncio
import json
import logging
import math
import os
import random
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import asdict, replace
from pathlib import Path
from .algorithm import VesselState, RiskConfig, align_live, evaluate, iso, displacement, xy, KNOT_TO_MPS
from .ais import AISDecoder, UDPReceiver, encode_position, encode_static
from .importer import state_at
from .scenarios import SCENARIOS, START_TS
from .motion_control import MotionController, DEFAULT_STOP_SETTINGS

log = logging.getLogger("ais")


class Engine:
    def __init__(self, db_path=None, udp_port=None, auto_stop_default=True):
        self.auto_stop_default=auto_stop_default
        self.config = RiskConfig()
        self.db_path = Path(db_path or os.getenv("AIS_DB_PATH", "data/ais-demo.db"))
        self.udp_port = int(udp_port if udp_port is not None else os.getenv("AIS_UDP_PORT", "10110"))
        self.udp_host = "127.0.0.1"
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()
        self.transport = self.sender = None
        self.task = None
        self.imported = None
        self.import_report = None
        self.speed = 1
        self.faults = {"asynchronous": False, "duplicate": False, "dropout": False}
        self.source = "simulation"
        self.scenario_id = "mixed"
        self.custom_scene = None
        self.running = False
        self.error = None

    async def start(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created_at TEXT, metadata TEXT, report TEXT);
            CREATE TABLE IF NOT EXISTS evaluations(run_id TEXT, timestamp REAL, target_mmsi TEXT, data TEXT);
            CREATE INDEX IF NOT EXISTS eval_run ON evaluations(run_id, timestamp);
            CREATE TABLE IF NOT EXISTS packets(run_id TEXT, timestamp REAL, direction TEXT, raw TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS positions(run_id TEXT, timestamp REAL, mmsi TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS custom_scenarios(id TEXT PRIMARY KEY, name TEXT, definition TEXT, updated_at TEXT);
        """)
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda:UDPReceiver(self.receive), local_addr=(self.udp_host,self.udp_port))
        self.udp_port = self.transport.get_extra_info("sockname")[1]
        self.sender, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, remote_addr=(self.udp_host,self.udp_port))
        await self.reset()
        self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        self.persist_report()
        for transport in (self.sender,self.transport):
            if transport: transport.close()
        self.db.close()

    def packet(self, direction, raw, status="ok"):
        entry = {"direction":direction,"time":iso(self.now),"raw":raw,"status":status}
        self.messages.appendleft(entry)
        self.db.execute("INSERT INTO packets VALUES (?,?,?,?,?)", (self.run_id,self.now,direction,raw,status))

    def receive(self, line, peer):
        self.stats["received"] += 1
        self.stats["bytes"] += len(line)
        try:
            decoded = self.decoder.parse(line, str(peer))
            self.packet("RX",line)
            if decoded is None: return
            self.stats["decoded"] += 1
            if decoded["kind"] != "position": return
            mmsi = decoded["mmsi"]
            ts = decoded["timestamp"]
            previous = self.latest.get(mmsi)
            if previous and ts < previous.timestamp:
                self.stats["out_of_order"] += 1
                return
            if previous and ts == previous.timestamp:
                self.stats["duplicates"] += 1
                return
            sog,cog = decoded["sog"],decoded["cog"]
            quality = "measured"
            if sog is None or cog is None:
                if not previous or ts <= previous.timestamp:
                    self.stats["invalid_motion"] += 1
                    return
                dx,dy = displacement(previous.latitude,previous.longitude,decoded["latitude"],decoded["longitude"])
                derived = math.hypot(dx,dy)/(ts-previous.timestamp)/KNOT_TO_MPS
                if derived >= 102.3: raise ValueError("补算航速异常")
                sog = derived if sog is None else sog
                cog = math.degrees(math.atan2(dx,dy))%360 if cog is None else cog
                quality = "derived_motion"
            state = VesselState(mmsi,ts,decoded["latitude"],decoded["longitude"],sog,cog,
                                decoded["ship_type"],decoded["nav_status"],decoded["name"],quality)
            self.latest[mmsi] = state
            self.trails.setdefault(mmsi,deque(maxlen=1200)).append([state.latitude,state.longitude])
            self.db.execute("INSERT INTO positions VALUES (?,?,?,?)",(self.run_id,ts,mmsi,json.dumps(state.public())))
        except Exception as exc:
            self.stats["errors"] += 1
            self.packet("ERR",line,str(exc))
        finally:
            self.changed.set()

    async def reset(self, save_previous=True):
        if save_previous and hasattr(self,"run_id"): self.persist_report()
        self.running = False
        self.elapsed = 0
        self.now = self.start_time
        self.run_id = uuid.uuid4().hex[:12]
        self.latest, self.trails, self.rows = {}, {}, []
        self.render_frames = deque(maxlen=65)
        self.metrics, self.histories, self.events = {}, {}, []
        self.messages = deque(maxlen=100)
        self.stats = dict.fromkeys(["sent","received","decoded","errors","duplicates","out_of_order","invalid_motion","bytes"],0)
        self.decoder = AISDecoder()
        settings=self.scene.get('auto_stop',{**DEFAULT_STOP_SETTINGS,'enabled':self.auto_stop_default}) if self.source=='simulation' else {}
        self.controller=MotionController(self.scene['ships'],self.own_mmsi,settings) if settings.get('enabled') else None
        self.error = None
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?)",(self.run_id,iso(time.time()),json.dumps(self.metadata(),ensure_ascii=False),None))
        self.db.commit()
        await self.tick(0)

    @property
    def start_time(self):
        if self.source == "import" and self.imported:
            return min(s.timestamp for states in self.imported.values() for s in states)
        return START_TS

    @property
    def scene(self):
        return self.custom_scene if self.scenario_id=="custom" and self.custom_scene else SCENARIOS[self.scenario_id]

    @property
    def duration(self):
        if self.source == "import" and self.imported:
            return int(max(s.timestamp for states in self.imported.values() for s in states)-self.start_time)
        return self.scene["duration"]

    @property
    def own_mmsi(self):
        return self.import_own if self.source == "import" else self.sim_own

    @property
    def sim_own(self):
        return getattr(self,"chosen_own",self.scene["ships"][0].mmsi)

    def definitions(self):
        if self.source == "import":
            return [{"mmsi":k,"name":v[0].name,"ship_type":v[0].ship_type,"ais_class":"A"} for k,v in self.imported.items()]
        return [{"mmsi":s.mmsi,"name":s.name,"ship_type":s.ship_type,"ais_class":s.ais_class} for s in self.scene["ships"]]

    def metadata(self):
        return {"algorithm_version":"document-v1.0","source":self.source,"synthetic":True if self.source=="simulation" else None,"scenario":self.scenario_id,
                "config":asdict(self.config),"own_mmsi":self.own_mmsi,"resample_seconds":1,
                "scene_definition":{**{k:v for k,v in self.scene.items() if k!="ships"},"ships":[asdict(s) for s in self.scene["ships"]]} if self.source=="simulation" else None,
                "alignment":"causal bounded extrapolation" if self.source=="simulation" else "offline bounded interpolation",
                "import":self.import_report if self.source=="import" else None,
                "motion_control":self.controller.public() if getattr(self,'controller',None) else {'enabled':False},
                "faults":self.faults,"warning_scope":"configured monitoring radius; document risk/distance rules",
                "timestamp_policy":"UTC stored; Asia/Shanghai display; NMEA c tag carries simulation/replay event time"}

    async def tick(self, elapsed):
        previous_elapsed=self.elapsed
        previous_progress=self.controller.progress.copy() if self.controller else None
        self.elapsed, self.now = elapsed, self.start_time+elapsed
        controlled=self.controller.advance(elapsed,self.now) if self.controller else None
        expected = []
        sent_before, received_before = self.stats["sent"], self.stats["received"]
        for i, definition in enumerate(self.definitions()):
            mmsi = definition["mmsi"]
            if self.source == "simulation":
                ship = self.scene["ships"][i]
                state = controlled[mmsi] if controlled else ship.state(elapsed)
                if self.faults["dropout"] and i==1 and 80 <= elapsed <= 140: continue
                if self.faults["asynchronous"] and elapsed and elapsed % (2+i%4) != i%(2+i%4): continue
            else:
                state = state_at(self.imported[mmsi],self.now,self.config.max_age_s)
                if state is None: continue
            if elapsed == 0 or elapsed%60 == 0:
                for line in encode_static(state,definition["ais_class"]): self.send(line)
            for line in encode_position(state,definition["ais_class"],mmsi==self.own_mmsi):
                self.send(line)
                if self.faults["duplicate"]: self.send(line)
            expected.append(mmsi)
        # Synchronize on received event timestamps, not an in-memory simulator state.
        deadline = time.monotonic()+.8
        expected_received = received_before+self.stats["sent"]-sent_before
        while self.stats["received"] < expected_received or not all(k in self.latest and self.latest[k].timestamp >= self.now-.001 for k in expected):
            remaining = deadline-time.monotonic()
            if remaining <= 0: break
            self.changed.clear()
            try: await asyncio.wait_for(self.changed.wait(),remaining)
            except asyncio.TimeoutError: break
        self.calculate()
        self.capture_render_frames(previous_elapsed,previous_progress)
        self.db.commit()

    def capture_render_frames(self,previous_elapsed,previous_progress):
        """Verified movement keyframes for rendering; AIS/risk retain 1 s sampling.

        Only describe motion already executed and received over UDP. Never send
        predicted future positions for the renderer to advance through a stop.
        """
        if self.source!='simulation' or self.scenario_id!='custom': return
        if any(self.faults.values()):
            self.render_frames.clear()
            return
        states={s.mmsi:self.aligned(s.mmsi) for s in self.scene['ships']}
        if any(s is None or abs(self.latest[mmsi].timestamp-self.now)>.001 for mmsi,s in states.items()): return
        steps=max(1,math.ceil((self.elapsed-previous_elapsed)*4))
        for i in range(1,steps+1):
            q=i/steps
            poses={}
            for ship in self.scene['ships']:
                state=states[ship.mmsi]
                old_clock=previous_progress[ship.mmsi] if previous_progress is not None else previous_elapsed
                new_clock=self.controller.progress[ship.mmsi] if self.controller else self.elapsed
                x,y,sog,cog=ship.motion_at(old_clock+(new_clock-old_clock)*q)
                if old_clock==new_clock or i==steps:
                    x,y=xy(state.latitude,state.longitude)
                    sog,cog=state.sog,state.cog
                poses[ship.mmsi]={k:round(v,5) for k,v in dict(x=x,y=y,sog=sog,cog=cog).items()}
            self.render_frames.append({'time':previous_elapsed+(self.elapsed-previous_elapsed)*q,'poses':poses})

    def send(self,line):
        self.sender.sendto((line+"\r\n").encode("ascii"))
        self.stats["sent"] += 1
        self.packet("TX",line)

    def aligned(self,mmsi):
        state = self.latest.get(mmsi)
        if state is None: return None
        if self.source == "import":
            # Offline gaps must not be silently bridged by a live extrapolation.
            if abs(state.timestamp-self.now) > .001: return None
        return align_live(state,self.now,self.config.max_age_s)

    def calculate(self):
        own = self.aligned(self.own_mmsi)
        metrics = {}
        for definition in self.definitions():
            mmsi = definition["mmsi"]
            if mmsi == self.own_mmsi: continue
            target = self.aligned(mmsi)
            if own is None or target is None:
                metrics[mmsi] = {"target_mmsi":mmsi,"data_quality":"stale","predicted_warning":False,"warning_reason":"数据过期或尚无有效状态"}
            else:
                row = evaluate(own,target,self.config)
                row["sample_age_s"] = self.now-self.latest[mmsi].timestamp
                row['own_sog']=own.sog
                row['target_sog']=target.sog
                row['own_held']=bool(self.controller and self.controller.held)
                row['target_held']=bool(self.controller and mmsi in self.controller.contact_holds)
                metrics[mmsi] = row
                self.rows.append(row)
                history = self.histories.setdefault(mmsi,deque(maxlen=7201))
                history.append({k:row[k] for k in ["time","collision_risk","risk_dcpa","risk_tcpa","risk_distance","actual_distance_m","dcpa_m","tcpa_s","predicted_warning"]})
                self.db.execute("INSERT INTO evaluations VALUES (?,?,?,?)",(self.run_id,self.now,mmsi,json.dumps(row)))
            active = next((e for e in reversed(self.events) if e["target_mmsi"]==mmsi and e["end_time"] is None),None)
            row = metrics[mmsi]
            if row["predicted_warning"]:
                if active is None:
                    active = {"id":len(self.events)+1,"target_mmsi":mmsi,"start_time":self.now,"end_time":None,
                              "reason":row["warning_reason"],"peak_risk":row["collision_risk"],"first_distance_m":row["actual_distance_m"],"end_reason":None}
                    self.events.append(active)
                    log.info("首次预警 target=%s risk=%.4f distance=%.1fm reason=%s",mmsi,row["collision_risk"],row["actual_distance_m"],row["warning_reason"])
                active["peak_risk"] = max(active["peak_risk"],row["collision_risk"])
            elif active:
                active["end_time"] = self.now
                active["end_reason"] = "数据过期，停止评估" if row.get("data_quality")=="stale" else "预警条件解除"
        self.metrics = metrics
        if self.elapsed%10 == 0 or not self.running: self.persist_report()

    async def loop(self):
        while True:
            started = time.monotonic()
            if self.running:
                try:
                    async with self.lock:
                        if self.elapsed < self.duration: await self.tick(self.elapsed+1)
                        else:
                            self.running = False
                            self.persist_report()
                            self.log_summary()
                except Exception as exc:
                    self.error, self.running = str(exc),False
                    log.exception("Simulation failed")
            await asyncio.sleep(max(.001, (1/self.speed if self.running else .1)-(time.monotonic()-started)))

    def snapshot(self):
        vessels = []
        for definition in self.definitions():
            mmsi = definition["mmsi"]
            state = self.aligned(mmsi)
            last = self.latest.get(mmsi)
            item = state or last
            if item:
                trail = list(self.trails.get(mmsi,[]))
                vessels.append({**item.public(),"name":definition["name"],"is_own":mmsi==self.own_mmsi,
                                "stale":state is None,"sample_age_s":self.now-last.timestamp,
                                "trail":trail[::max(1,len(trail)//250)],"risk":self.metrics.get(mmsi),
                                "x":xy(item.latitude,item.longitude)[0],"y":xy(item.latitude,item.longitude)[1],
                                "trajectory_xy":[xy(*p) for p in trail[::max(1,len(trail)//250)]] if self.scenario_id=="custom" else []})
        return {"run_id":self.run_id,"running":self.running,"elapsed":self.elapsed,"duration":self.duration,
                "time":self.now,"time_iso":iso(self.now),"scenario":self.scenario_id,"source":self.source,
                "scenario_name":self.scene["name"],
                "motion_control":self.controller.public() if self.controller else {'enabled':False},
                "render_frames":list(self.render_frames),
                "scene_definition":self.metadata()["scene_definition"],
                "speed":self.speed,"config":asdict(self.config),"faults":self.faults,"own_mmsi":self.own_mmsi,
                "vessels":vessels,"definitions":self.definitions(),"events":self.events[-100:],
                "stats":self.stats,"udp":f"{self.udp_host}:{self.udp_port}","messages":list(self.messages)[:40],
                "histories":{k:list(v)[-600:] for k,v in self.histories.items()},"error":self.error,
                "import_report":self.import_report if self.source=="import" else None}

    def report(self):
        results = []
        for mmsi in {r["target_mmsi"] for r in self.rows}:
            rows = [r for r in self.rows if r["target_mmsi"]==mmsi]
            warned = [r for r in rows if r["predicted_warning"]]
            first, peak, closest = warned[0] if warned else None,max(rows,key=lambda r:r["collision_risk"]),min(rows,key=lambda r:r["actual_distance_m"])
            results.append({"target_mmsi":mmsi,"first_warning":first,"peak_risk":peak,
                            "closest_observed":closest,"warning_sample_count":len(warned),
                            "warning_lead_time_to_observed_closest_s":closest["time"]-first["time"] if first else None})
        return {"run_id":self.run_id,"metadata":self.metadata(),"start_time":iso(self.start_time),
                "end_time":iso(self.now),"complete":self.elapsed>=self.duration,"evaluation_count":len(self.rows),
                "event_count":len(self.events),"events":self.events,"targets":sorted(results,key=lambda r:r["target_mmsi"]),
                "transport_stats":self.stats,"note":"最近会遇为当前已接收有效数据的观测最小距离；完整回放结束后才代表全时窗。综合风险是规则得分，不是碰撞概率。"}

    def persist_report(self):
        if not hasattr(self,"db") or not hasattr(self,"rows"): return
        self.db.execute("UPDATE runs SET report=? WHERE id=?",(json.dumps(self.report(),ensure_ascii=False),self.run_id))
        self.db.commit()

    def log_summary(self):
        report=self.report()
        log.info("运行摘要 run=%s source=%s time=%s..%s evaluations=%d events=%d complete=%s",self.run_id,self.source,report['start_time'],report['end_time'],report['evaluation_count'],report['event_count'],report['complete'])
        for target in report['targets']:
            first=target['first_warning']
            log.info("目标=%s 首次预警=%s 峰值风险=%.4f 最近观测距离=%.1fm 提前量=%ss",target['target_mmsi'],first['timestamp'] if first else '无',target['peak_risk']['collision_risk'],target['closest_observed']['actual_distance_m'],target['warning_lead_time_to_observed_closest_s'])
