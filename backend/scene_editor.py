"""Editable two-vessel encounter definitions shared by preview and simulation."""
from dataclasses import asdict
from math import acos, cos, degrees, radians, hypot
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .algorithm import RiskConfig, evaluate, velocity
from .scenarios import Ship


class Waypoint(BaseModel):
    x: float = Field(ge=-10000,le=10000,allow_inf_nan=False)
    y: float = Field(ge=-10000,le=10000,allow_inf_nan=False)


class StopSettings(BaseModel):
    enabled: bool=True
    stop_distance_m: float=Field(default=350,ge=50,le=2000)
    resume_distance_m: float=Field(default=600,ge=100,le=5000)
    lookahead_s: int=Field(default=30,ge=1,le=120)
    safe_duration_s: int=Field(default=5,ge=1,le=30)

    @model_validator(mode='after')
    def hysteresis(self):
        if self.resume_distance_m<=self.stop_distance_m:
            raise ValueError('恢复距离必须大于停车保护距离')
        return self


class EditableShip(BaseModel):
    mmsi: str = Field(pattern=r"^\d{9}$")
    name: str = Field(min_length=1, max_length=40)
    x: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    y: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    sog: float = Field(ge=0, le=60, allow_inf_nan=False)
    cog: float = Field(ge=0, lt=360, allow_inf_nan=False)
    ship_type: int = Field(default=30, ge=0, le=255)
    ais_class: str = Field(default="B", pattern="^[AB]$")
    nav_status: int = Field(default=0, ge=0, le=15)
    waypoints: list[Waypoint] = Field(default_factory=list,max_length=32)
    interpolation: Literal['smooth','linear']='smooth'

    @model_validator(mode='after')
    def distinct_points(self):
        previous=(self.x,self.y)
        for waypoint in self.waypoints:
            if hypot(waypoint.x-previous[0],waypoint.y-previous[1])<1:
                raise ValueError('相邻航点之间至少相距 1 米')
            previous=(waypoint.x,waypoint.y)
        return self


class SceneDefinition(BaseModel):
    name: str = Field(default="自定义双船会遇", min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    duration: int = Field(default=600, ge=30, le=3600)
    ships: list[EditableShip] = Field(min_length=2, max_length=2)
    auto_stop: StopSettings = Field(default_factory=StopSettings)

    @model_validator(mode="after")
    def check_identity(self):
        if self.ships[0].mmsi == self.ships[1].mmsi:
            raise ValueError("两艘船的 MMSI 不能相同")
        if not self.name.strip() or any(not s.name.strip() for s in self.ships):
            raise ValueError("场景名和船名不能为空")
        if self.auto_stop.enabled and hypot(self.ships[0].x-self.ships[1].x,self.ships[0].y-self.ships[1].y)<100:
            raise ValueError('两船初始间距至少为 100 米，请调整摆放位置')
        return self

    def runtime_scene(self):
        return {"name":self.name, "description":self.description, "duration":self.duration,
                "auto_stop":self.auto_stop.model_dump(),
                "ships":[Ship(**s.model_dump()) for s in self.ships]}


def preview(scene: SceneDefinition, config: RiskConfig):
    own, target = scene.runtime_scene()["ships"]
    metrics = evaluate(own.state(0), target.state(0), config)
    angle = degrees(acos(max(-1., min(1., cos(radians(own.state(0).cog-target.state(0).cog))))))
    return {"scene":scene.model_dump(), "metrics":metrics, "heading_angle_deg":round(angle,2),
            "routes":[{'mmsi':s.mmsi,'length_m':s.route.length if s.route else None,'points':s.route.public_points() if s.route else []} for s in [own,target]]}


def encounter(angle, side="right"):
    own_cog = 90
    target_cog = (own_cog-angle if side=="right" else own_cog+angle)%360
    ovx,ovy = velocity(10,own_cog)
    tvx,tvy = velocity(10,target_cog)
    return [Ship("413000001","本船",round(-ovx*240),round(-ovy*240),10,own_cog,70,"A"),
            Ship("413000101","目标船",round(-tvx*240),120 if angle==180 else round(-tvy*240),10,target_cog)]


def definition(name, ships, description="", duration=600):
    return {"name":name,"description":description,"duration":duration,"auto_stop":StopSettings().model_dump(),
            "ships":[{k:v for k,v in asdict(s).items() if k!="turns"} for s in ships]}


def cases():
    result=[]
    for angle in (30,45,60,90,120,150,180):
        name="正面对遇 · 180°" if angle==180 else f"交叉会遇 · {angle}°"
        description="两船相向驶近，观察预警提前量。" if angle==180 else f"两船航向夹角 {angle}°，按当前航速驶向同一会遇区域。"
        result.append({"id":f"angle_{angle}","category":"对遇" if angle==180 else "交叉",
                       "angle":angle,"scene":definition(name,encounter(angle),description)})
    result.append({"id":"left_90","category":"交叉","angle":90,
                   "scene":definition("左侧交叉 · 90°",encounter(90,"left"),"从本船另一侧驶近，比较左右交叉的风险变化。")})
    result.append({"id":"overtaking","category":"追越","angle":0,
                   "scene":definition("同向追越",[Ship("413000001","本船",-1200,0,12,90,70,"A"),Ship("413000101","目标船",-300,80,6,90)],"本船航速较快，逐渐接近前方慢船。")})
    result.append({"id":"parallel","category":"安全通过","angle":0,
                   "scene":definition("平行同速",[Ship("413000001","本船",-1200,-350,10,90,70,"A"),Ship("413000101","目标船",-700,350,10,90)],"相对速度为零，距离保持稳定。")})
    result.append({"id":"safe_crossing","category":"安全通过","angle":90,
                   "scene":definition("错位安全交叉",[Ship("413000001","本船",-1235,0,10,90,70,"A"),Ship("413000101","目标船",1500,-1235,10,0)],"两船的通过时间错开，预测间距较大。")})
    own=Ship('413000001','本船',-1700,-200,10,90,70,'A',waypoints=[{'x':-700,'y':-200},{'x':100,'y':200},{'x':1700,'y':250}])
    target=Ship('413000101','目标船',300,-1600,8,0,waypoints=[{'x':300,'y':-500},{'x':0,'y':400},{'x':-200,'y':1800}])
    result.append({'id':'curved_crossing','category':'曲线','scene':definition('曲线交叉会遇',[own,target],'两船沿平滑曲线接近，主船停车等待后沿原曲线续航。',900)})
    own=Ship('413000001','本船',-1800,-700,10,90,70,'A',waypoints=[{'x':-700,'y':-650},{'x':0,'y':400},{'x':900,'y':-200},{'x':1900,'y':500}])
    target=Ship('413000101','目标船',1600,1200,7,240,waypoints=[{'x':1000,'y':1000},{'x':300,'y':200},{'x':-500,'y':-200},{'x':-1600,'y':-700}])
    result.append({'id':'s_curve','category':'曲线','scene':definition('S 形航迹会遇',[own,target],'设置多个航点拟合 S 形航迹，观察航向随曲线变化。',1200)})
    own=Ship('413000001','本船',-1700,-400,9,90,70,'A',waypoints=[{'x':-700,'y':-600},{'x':300,'y':-250},{'x':1700,'y':-400}])
    target=Ship('413000101','目标船',1500,1300,8,270,waypoints=[{'x':500,'y':1800},{'x':-800,'y':1300},{'x':-1700,'y':1700}])
    result.append({'id':'curved_safe','category':'曲线','scene':definition('曲线安全通过',[own,target],'两船在分开的曲线上运动，抵达终点航点后停船。',1000)})
    return result
