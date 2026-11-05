import asyncio
import json
import logging
import uuid
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .algorithm import RiskConfig, iso
from .scene_editor import SceneDefinition, cases, preview
from .engine import Engine
from .exporter import bundle, csv_bytes, plot_png
from .importer import load_tracks
from .scenarios import SCENARIOS, catalog

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
engine=Engine()
ROOT=Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app):
    await engine.start()
    yield
    await engine.close()


app=FastAPI(title="海际 AIS 预警 Demo",version="1.0.0",lifespan=lifespan)


class Control(BaseModel):
    action: Literal["play","pause","reset","step","seek","complete","next_warning"]
    elapsed: int=Field(default=0,ge=0,le=7200)
    speed: Literal[1,2,5,10,20]|None=None


class ScenarioSelection(BaseModel):
    id: str


class SimulationRequest(BaseModel):
    scene: SceneDefinition
    autoplay: bool=True
    speed: Literal[1,2,5,10,20]=10


class Settings(BaseModel):
    monitor_radius_nm: float=Field(default=2,ge=.25,le=10)
    distance_high_m: float=Field(default=300,ge=0,le=10000)
    distance_low_m: float=Field(default=1000,gt=0,le=20000)
    time_high_s: float=Field(default=60,ge=0,le=3600)
    time_low_s: float=Field(default=240,gt=0,le=7200)
    risk_threshold: float=Field(default=.72,gt=0,le=1)
    emergency_distance_m: float=Field(default=350,ge=0,le=18520)
    max_age_s: float=Field(default=30,ge=1,le=120)

    @model_validator(mode="after")
    def check_ranges(self):
        if self.distance_low_m<=self.distance_high_m or self.time_low_s<=self.time_high_s:
            raise ValueError("低风险边界必须大于高风险边界")
        if self.emergency_distance_m>self.monitor_radius_nm*1852:
            raise ValueError("紧急距离不能超出监测半径")
        return self


class FaultSettings(BaseModel):
    asynchronous: bool=False
    duplicate: bool=False
    dropout: bool=False


@app.get("/api/health")
async def health():
    return {"ok":True,"udp":f"{engine.udp_host}:{engine.udp_port}","source":engine.source}


@app.get("/api/scenarios")
async def scenarios(): return catalog()


@app.get("/api/state")
async def state():
    async with engine.lock:
        return engine.snapshot()


@app.get("/api/cases")
async def case_library(): return cases()


@app.post("/api/scene/preview")
async def preview_scene(value:SceneDefinition):
    return preview(value,engine.config)


@app.post("/api/simulation")
async def simulate_scene(value:SimulationRequest):
    async with engine.lock:
        engine.persist_report()
        engine.source="simulation"
        engine.scenario_id="custom"
        engine.custom_scene=value.scene.runtime_scene()
        engine.chosen_own=value.scene.ships[0].mmsi
        engine.faults={"asynchronous":False,"duplicate":False,"dropout":False}
        engine.speed=value.speed
        await engine.reset(save_previous=False)
        engine.running=value.autoplay
    return engine.snapshot()


@app.get("/api/custom-scenarios")
async def saved_scenes():
    return [{"id":r[0],"scene":json.loads(r[1]),"updated_at":r[2]} for r in engine.db.execute("SELECT id,definition,updated_at FROM custom_scenarios ORDER BY updated_at DESC")]


@app.post("/api/custom-scenarios")
async def save_scene(value:SceneDefinition):
    scene_id=uuid.uuid4().hex[:12]
    engine.db.execute("INSERT INTO custom_scenarios VALUES (?,?,?,?)",(scene_id,value.name,json.dumps(value.model_dump(),ensure_ascii=False),iso(time.time())))
    engine.db.commit()
    return {"id":scene_id,"scene":value.model_dump()}


@app.delete("/api/custom-scenarios/{scene_id}")
async def delete_scene(scene_id:str):
    cursor=engine.db.execute("DELETE FROM custom_scenarios WHERE id=?",(scene_id,))
    engine.db.commit()
    if not cursor.rowcount: raise HTTPException(404,"场景不存在")
    return {"ok":True}


@app.post("/api/control")
async def control(command:Control):
    async with engine.lock:
        if command.speed: engine.speed=command.speed
        action=command.action
        if action=="play":
            if engine.elapsed>=engine.duration: await engine.reset()
            engine.running=True
        elif action=="pause":
            engine.running=False
            engine.persist_report()
        elif action=="reset": await engine.reset()
        elif action=="step":
            engine.running=False
            if engine.elapsed<engine.duration: await engine.tick(engine.elapsed+1)
        elif action in ("seek","complete","next_warning"):
            engine.running=False
            desired=engine.duration if action in ("complete","next_warning") else min(command.elapsed,engine.duration)
            if desired<engine.elapsed: await engine.reset()
            for elapsed in range(engine.elapsed+1,desired+1):
                if action=="next_warning" and any(r.get("predicted_warning") for r in engine.metrics.values()): break
                await engine.tick(elapsed)
            engine.persist_report()
            engine.log_summary()
    return engine.snapshot()


@app.post("/api/scenario")
async def select_scenario(command:ScenarioSelection):
    if command.id not in SCENARIOS: raise HTTPException(400,"场景不存在")
    async with engine.lock:
        engine.persist_report()
        engine.source="simulation"
        engine.scenario_id=command.id
        engine.chosen_own=SCENARIOS[command.id]["ships"][0].mmsi
        await engine.reset(save_previous=False)
    return engine.snapshot()


@app.put("/api/settings")
async def settings(value:Settings):
    async with engine.lock:
        engine.persist_report()
        engine.config=RiskConfig(**value.model_dump())
        await engine.reset(save_previous=False)
    return engine.snapshot()


@app.put("/api/faults")
async def faults(value:FaultSettings):
    async with engine.lock:
        engine.persist_report()
        engine.faults=value.model_dump()
        await engine.reset(save_previous=False)
    return engine.snapshot()


@app.post("/api/own/{mmsi}")
async def own(mmsi:str):
    if mmsi not in [s["mmsi"] for s in engine.definitions()]: raise HTTPException(400,"本船必须来自当前场景")
    async with engine.lock:
        engine.persist_report()
        if engine.source=="import": engine.import_own=mmsi
        else: engine.chosen_own=mmsi
        await engine.reset(save_previous=False)
    return engine.snapshot()


@app.post("/api/import")
async def import_file(file:UploadFile=File(...),own_mmsi:str=Form("")):
    content=await file.read(8*1024*1024+1)
    if len(content)>8*1024*1024: raise HTTPException(400,"文件大小不能超过 8 MB")
    try:
        tracks,report=load_tracks(content,file.filename or "")
        if own_mmsi and own_mmsi not in tracks: raise ValueError("指定本船 MMSI 不在文件中")
        start=min(s.timestamp for v in tracks.values() for s in v)
        end=max(s.timestamp for v in tracks.values() for s in v)
        if end-start>7200: raise ValueError("Demo 单次回放最长 2 小时，请先截取会遇时间窗")
        if end<=start: raise ValueError("轨迹需要包含至少两个不同时间点")
    except Exception as exc: raise HTTPException(400,str(exc)) from exc
    async with engine.lock:
        engine.persist_report()
        engine.source="import"
        engine.imported,engine.import_report=tracks,{**report,"filename":file.filename}
        engine.import_own=own_mmsi or next(iter(tracks))
        await engine.reset(save_previous=False)
    return engine.snapshot()


@app.get("/api/report")
async def report(): return engine.report()


@app.get("/api/runs")
async def runs():
    return [{"id":r[0],"created_at":r[1],"metadata":json.loads(r[2])} for r in engine.db.execute("SELECT id,created_at,metadata FROM runs ORDER BY created_at DESC LIMIT 50")]


@app.get("/api/runs/{run_id}/report")
async def previous_report(run_id:str):
    row=engine.db.execute("SELECT report FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row or row[0] is None: raise HTTPException(404,"报告不存在")
    return json.loads(row[0])


@app.get("/api/export/{kind}")
async def export(kind:Literal["csv","json","png","zip"]):
    async with engine.lock:
        if not engine.rows: raise HTTPException(400,"尚无有效双船评估记录")
        if kind=="csv": data,media=csv_bytes(engine.rows),"text/csv; charset=utf-8"
        elif kind=="json": data,media=json.dumps(engine.report(),ensure_ascii=False,indent=2).encode(),"application/json"
        elif kind=="png": data,media=plot_png(engine),"image/png"
        else: data,media=bundle(engine),"application/zip"
    return Response(data,media_type=media,headers={"Content-Disposition":f'attachment; filename="ais-{engine.run_id}.{kind}"'})


@app.get("/api/sample.csv")
async def sample():
    rows=[]
    for elapsed in range(0,601,5):
        for ship in SCENARIOS["mixed"]["ships"]:
            s=ship.state(elapsed).public()
            s["timestamp"]=s["timestamp_iso"]
            rows.append(s)
    fields=["mmsi","timestamp","latitude","longitude","sog","cog","ship_type","nav_status","name"]
    return Response(csv_bytes(rows,fields),media_type="text/csv",headers={"Content-Disposition":'attachment; filename="synthetic-ais-sample.csv"'})


@app.websocket("/ws")
async def websocket(ws:WebSocket):
    await ws.accept()
    previous=None
    last_sent=0.
    try:
        while True:
            # A snapshot must not expose the controller for the next tick with
            # AIS positions from the previous tick while UDP is being decoded.
            async with engine.lock:
                state=engine.snapshot()
            serialized=json.dumps(state,ensure_ascii=False,separators=(',',':'))
            if serialized!=previous or time.monotonic()-last_sent>=5:
                await ws.send_text(serialized)
                previous=serialized
                last_sent=time.monotonic()
            await asyncio.sleep(.1)
    except (WebSocketDisconnect,RuntimeError,ConnectionError): pass


if (ROOT/"dist/assets").exists(): app.mount("/assets",StaticFiles(directory=ROOT/"dist/assets"),name="assets")


@app.get("/")
async def index():
    if (ROOT/"dist/index.html").exists(): return FileResponse(ROOT/"dist/index.html")
    return {"message":"前端尚未构建。运行 npm run build，或 npm run dev 后访问 http://127.0.0.1:5173","docs":"/docs"}
