"""Deterministic synthetic scenarios. Tracks are generated motion, not manoeuvre advice."""
from dataclasses import dataclass, field
from functools import cached_property
from .routes import FittedRoute
from .algorithm import VesselState, latlon, velocity

START_TS = 1793844000.0  # 2026-11-05 02:00 UTC / 10:00 China Standard Time


@dataclass
class Ship:
    mmsi: str
    name: str
    x: float
    y: float
    sog: float
    cog: float
    ship_type: int = 30
    ais_class: str = "B"
    nav_status: int = 0
    turns: list = field(default_factory=list)
    waypoints: list = field(default_factory=list)
    interpolation: str = "smooth"

    @cached_property
    def route(self):
        return FittedRoute([(self.x,self.y)]+[(p['x'],p['y']) for p in self.waypoints],self.interpolation=="smooth") if self.waypoints else None

    def motion_at(self, elapsed):
        if self.route:
            distance=max(0,elapsed)*self.sog*1852/3600
            x,y,cog=self.route.at_distance(distance)
            return x,y,0. if distance>=self.route.length-1e-6 else self.sog,cog
        x,y,speed,course,previous=self.x,self.y,self.sog,self.cog,0
        for at,new_speed,new_course in self.turns:
            if elapsed<=at: break
            vx,vy=velocity(speed,course)
            x,y=x+vx*(at-previous),y+vy*(at-previous)
            speed,course,previous=new_speed,new_course,at
        vx,vy=velocity(speed,course)
        return x+vx*(elapsed-previous),y+vy*(elapsed-previous),speed,course

    def state(self, elapsed: float) -> VesselState:
        x,y,speed,course=self.motion_at(elapsed)
        lat,lon=latlon(x,y)
        return VesselState(self.mmsi, START_TS+elapsed, lat, lon, speed, course,
                           self.ship_type, self.nav_status if self.ais_class == "A" else None, self.name)


def own():
    return Ship("413000001", "海巡演示 01", -1600, 0, 12, 90, 70, "A")


SCENARIOS = {
    "mixed": {"name": "多船综合会遇", "description": "交叉、对遇、平行与安全通过同时出现，观察各目标独立风险。", "duration": 600,
              "ships": [own(), Ship("413000101", "浙渔演示 101", -118, -900, 7, 0),
                        Ship("413000102", "浙渔演示 102", 1600, 140, 10, 270),
                        Ship("413000103", "浙渔演示 103", -1200, 700, 12, 90),
                        Ship("413000104", "浙渔演示 104", 1500, -1600, 6, 20),
                        Ship("413000105", "货船演示 105", 2000, 1500, 8, 90, 70, "A")]},
    "head_on": {"name": "对遇接近", "description": "两船相向航行，先风险预警，再进入距离保护范围。", "duration": 600,
                "ships": [own(), Ship("413000102", "浙渔演示 102", 1600, 100, 10, 270)]},
    "crossing": {"name": "交叉会遇", "description": "接近交叉点时风险上升，通过最近会遇点后时间风险归零。", "duration": 600,
                 "ships": [own(), Ship("413000101", "浙渔演示 101", -118, -900, 7, 0)]},
    "overtaking": {"name": "追越接近", "description": "较快本船逐渐接近前方慢船，检验追越风险。", "duration": 600,
                   "ships": [own(), Ship("413000106", "浙渔演示 106", -400, 80, 5, 90)]},
    "parallel": {"name": "同向同速", "description": "相对速度为零；TCPA 无有效值，保持距离，不产生虚假紧迫预警。", "duration": 600,
                 "ships": [own(), Ship("413000103", "浙渔演示 103", -1200, 700, 12, 90)]},
    "receding": {"name": "会遇后驶离", "description": "最近会遇点已过去，TCPA 为负且距离大于 350 米，时间风险被抑制。", "duration": 300,
                 "ships": [own(), Ship("413000107", "浙渔演示 107", -2100, 100, 10, 270)]},
    "emergency": {"name": "近距离保护", "description": "目标已在 350 米内且正在驶离，仍按文档触发距离保护。", "duration": 180,
                  "ships": [own(), Ship("413000108", "浙渔演示 108", -1830, 100, 10, 270)]},
    "safe": {"name": "安全交叉", "description": "预测最近距离大于 1000 米，检验安全通过。", "duration": 600,
             "ships": [own(), Ship("413000109", "浙渔演示 109", 1500, 1000, 6, 0)]},
}


def catalog():
    return [{"id": key, **{k:v for k,v in scene.items() if k != "ships"},
             "vessel_count": len(scene["ships"])} for key, scene in SCENARIOS.items()]
