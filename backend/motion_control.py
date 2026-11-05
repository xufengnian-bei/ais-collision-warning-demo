"""Simulation-only stop/wait/resume. Risk evaluation remains independent."""
from dataclasses import replace
from functools import lru_cache
from math import ceil, hypot
from .algorithm import iso

DEFAULT_STOP_SETTINGS={'enabled':True,'stop_distance_m':350.,'resume_distance_m':600.,'lookahead_s':30,'safe_duration_s':5}


def segment_distance(a,b,point):
    vx,vy=b[0]-a[0],b[1]-a[1]
    vv=vx*vx+vy*vy
    q=max(0.,min(1.,((point[0]-a[0])*vx+(point[1]-a[1])*vy)/vv)) if vv else 0.
    return hypot(a[0]+q*vx-point[0],a[1]+q*vy-point[1])


class MotionController:
    def __init__(self,ships,own_mmsi,settings):
        self.ships=ships
        self.own=next(s for s in ships if s.mmsi==own_mmsi)
        self.targets=[s for s in ships if s.mmsi!=own_mmsi]
        self.settings=settings
        self.progress={s.mmsi:0. for s in ships}
        self.held=False
        self.safe_seconds=0.
        self.events=[]
        self.last_elapsed=0.
        self.contact_holds=[]
        self.reason="沿原航迹航行"
        by_mmsi={s.mmsi:s for s in ships}
        self.pose=lru_cache(maxsize=16384)(lambda mmsi,clock:by_mmsi[mmsi].motion_at(clock))
        # Do not park on a target's approaching route. This horizon is separate
        # from the configurable moving-vessel CPA check.
        self.parking_lookahead=max(180,settings['lookahead_s'])
        self.clearances={t.mmsi:min(settings['stop_distance_m'],hypot(self.own.x-t.x,self.own.y-t.y)) for t in self.targets}

    def ahead_distance(self,own_clock,target,target_clock):
        minimum=float('inf')
        for t in range(self.settings['lookahead_s']+1):
            a=self.pose(self.own.mmsi,own_clock+t)
            b=self.pose(target.mmsi,target_clock+t)
            minimum=min(minimum,hypot(a[0]-b[0],a[1]-b[1]))
        return minimum

    def parking_distance(self,own_clock,target,target_clock):
        position=self.pose(self.own.mmsi,own_clock)
        previous=self.pose(target.mmsi,target_clock)
        minimum=hypot(position[0]-previous[0],position[1]-previous[1])
        for t in range(1,self.parking_lookahead+1):
            current=self.pose(target.mmsi,target_clock+t)
            minimum=min(minimum,segment_distance(previous,current,position))
            previous=current
        return minimum

    def swept_distance(self,own_clock,own_delta,target,target_clock,target_delta):
        # Check the entire movement interval, including curved paths and fast
        # ships. Relative path segments are sampled at <= 0.5 m of travel.
        travel=max(self.own.sog*own_delta,target.sog*target_delta)*1852/3600
        steps=max(4,ceil(travel/.5))
        previous=None
        minimum=float('inf')
        for i in range(steps+1):
            q=i/steps
            a=self.pose(self.own.mmsi,own_clock+own_delta*q)
            b=self.pose(target.mmsi,target_clock+target_delta*q)
            relative=(a[0]-b[0],a[1]-b[1])
            minimum=min(minimum,segment_distance(previous,relative,(0,0)) if previous else hypot(*relative))
            previous=relative
        return minimum

    def record(self,kind,timestamp,message):
        self.events.append({'kind':kind,'time':timestamp,'timestamp':iso(timestamp),'message':message,'route_time_s':self.progress[self.own.mmsi]})

    def advance(self,elapsed,timestamp):
        dt=max(0,elapsed-self.last_elapsed)
        self.last_elapsed=elapsed
        own_clock=self.progress[self.own.mmsi]
        own_position=self.pose(self.own.mmsi,own_clock)
        threats=[t for t in self.targets if self.ahead_distance(own_clock,t,self.progress[t.mmsi])<=self.settings['stop_distance_m']]
        parking_threats=[t for t in self.targets if self.parking_distance(own_clock+dt,t,self.progress[t.mmsi])<self.settings['stop_distance_m']+1.]
        if self.held:
            clear=all(hypot(own_position[0]-self.pose(t.mmsi,self.progress[t.mmsi])[0],own_position[1]-self.pose(t.mmsi,self.progress[t.mmsi])[1])>=self.settings['resume_distance_m'] for t in self.targets) and not threats and not parking_threats
            self.safe_seconds=self.safe_seconds+dt if clear else 0.
            if clear and self.safe_seconds>=self.settings['safe_duration_s']:
                self.held=False
                self.reason='间距恢复安全，沿原航迹续航'
                self.record('resume',timestamp,self.reason)
        elif (threats or parking_threats) and own_position[2]>0:
            self.held=True
            self.safe_seconds=0.
            self.reason=(f"停车位置将占用目标船未来航路，主船提前在 {self.settings['stop_distance_m']:g} m 保护范围外等待" if parking_threats else f"预计 {self.settings['lookahead_s']} 秒内进入 {self.settings['stop_distance_m']:g} m 保护范围，主船停车等待")
            self.record('stop',timestamp,self.reason)
        own_delta=0. if self.held else dt
        # Recheck accepted movement, not just a future estimate. Stop the own
        # ship first, then any target that cannot pass the stationary ship.
        if own_delta and any(self.swept_distance(own_clock,own_delta,t,self.progress[t.mmsi],dt)<self.clearances[t.mmsi]-1e-6 for t in self.targets):
            own_delta=0.
            if not self.held:
                self.held=True
                self.safe_seconds=0.
                self.reason='本步运动将进入保护范围，主船停车等待'
                self.record('stop',timestamp,self.reason)
        self.progress[self.own.mmsi]+=own_delta
        own_next=self.pose(self.own.mmsi,self.progress[self.own.mmsi])
        previous_holds=set(self.contact_holds)
        self.contact_holds=[]
        for target in self.targets:
            old_clock=self.progress[target.mmsi]
            if self.swept_distance(own_clock,own_delta,target,old_clock,dt)<self.clearances[target.mmsi]-1e-6:
                self.contact_holds.append(target.mmsi)
            else:
                self.progress[target.mmsi]+=dt
        for mmsi in set(self.contact_holds)-previous_holds:
            self.record('target_stop',timestamp,f'目标船 {mmsi} 将进入本船保护范围，目标船同步停车，等待航路清空')
        for mmsi in previous_holds-set(self.contact_holds):
            self.record('target_resume',timestamp,f'目标船 {mmsi} 前方保护范围已清空，沿原航迹续航')
        if self.contact_holds: self.reason=f'目标无法在 {self.settings["stop_distance_m"]:g} m 保护距离外通过，双方停车等待；可修改航点留出通道'
        elif not self.held and own_next[2]<=0: self.reason='已到达终点航点' if self.own.route else '主船航速为零'
        states={}
        for ship in self.ships:
            state=replace(ship.state(self.progress[ship.mmsi]),timestamp=timestamp)
            if ship.mmsi in self.contact_holds or (ship.mmsi==self.own.mmsi and self.held): state=replace(state,sog=0.)
            states[ship.mmsi]=state
        return states

    def public(self):
        return {'enabled':True,'own_held':self.held,'reason':self.reason,'safe_seconds':self.safe_seconds,
                'settings':self.settings,'events':self.events,'route_times':self.progress.copy(),'contact_holds':self.contact_holds.copy(),
                'parking_lookahead_s':self.parking_lookahead,'protected_distances_m':self.clearances}
