"""The document's formulas, using metres, seconds and true-north COG."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from math import atan2, cos, degrees, hypot, radians, sin
from pyproj import CRS, Transformer, Geod

KNOT_TO_MPS = 1852 / 3600
ORIGIN = (31.1, 122.2)
_local = CRS.from_proj4(f"+proj=aeqd +lat_0={ORIGIN[0]} +lon_0={ORIGIN[1]} +datum=WGS84 +units=m")
_forward = Transformer.from_crs("EPSG:4326", _local, always_xy=True)
_inverse = Transformer.from_crs(_local, "EPSG:4326", always_xy=True)
_geod = Geod(ellps="WGS84")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def xy(lat: float, lon: float) -> tuple[float, float]:
    return _forward.transform(lon, lat)


def latlon(x: float, y: float) -> tuple[float, float]:
    lon, lat = _inverse.transform(x, y)
    return lat, lon


def velocity(sog: float, cog: float) -> tuple[float, float]:
    u = sog * KNOT_TO_MPS
    return u * sin(radians(cog)), u * cos(radians(cog))


def displacement(a_lat, a_lon, b_lat, b_lon):
    """True-north east/north displacement, valid for imported locations worldwide."""
    azimuth, _, distance = _geod.inv(a_lon,a_lat,b_lon,b_lat)
    return distance*sin(radians(azimuth)), distance*cos(radians(azimuth))


def move(latitude, longitude, east, north):
    lon,lat,_ = _geod.fwd(longitude,latitude,degrees(atan2(east,north)),hypot(east,north))
    return lat,lon


@dataclass
class VesselState:
    mmsi: str
    timestamp: float
    latitude: float
    longitude: float
    sog: float
    cog: float
    ship_type: int | None = None
    nav_status: int | None = None
    name: str = ""
    quality: str = "measured"

    def public(self):
        return {**asdict(self), "timestamp_iso": iso(self.timestamp)}


@dataclass
class RiskConfig:
    distance_high_m: float = 300
    distance_low_m: float = 1000
    time_high_s: float = 60
    time_low_s: float = 240
    risk_threshold: float = .72
    emergency_distance_m: float = 350
    monitor_radius_nm: float = 2
    max_age_s: float = 30


def z_risk(x: float, a: float, b: float) -> float:
    if b <= a:
        raise ValueError("低风险边界必须大于高风险边界")
    if x <= a:
        return 1.
    if x >= b:
        return 0.
    q = (x - a) / (b - a)
    return 1 - 2*q*q if q < .5 else 2*(1-q)**2


def align_live(state: VesselState, timestamp: float, max_age_s: float) -> VesselState | None:
    """Causal alignment: only past data, bounded constant-velocity extrapolation."""
    age = timestamp - state.timestamp
    if age < -.001 or age > max_age_s:
        return None
    vx, vy = velocity(state.sog, state.cog)
    lat, lon = move(state.latitude,state.longitude,vx*age,vy*age)
    return replace(state, latitude=lat, longitude=lon, timestamp=timestamp,
                   quality="extrapolated" if age > .01 else state.quality)


def evaluate(own: VesselState, target: VesselState, config: RiskConfig) -> dict:
    ovx, ovy = velocity(own.sog, own.cog)
    tvx, tvy = velocity(target.sog, target.cog)
    rx, ry = displacement(own.latitude,own.longitude,target.latitude,target.longitude)
    vx, vy = tvx-ovx, tvy-ovy
    distance = hypot(rx, ry)
    vv = vx*vx + vy*vy
    tcpa = -(rx*vx + ry*vy)/vv if vv > 1e-8 else None
    dcpa = hypot(rx + tcpa*vx, ry + tcpa*vy) if tcpa is not None else distance
    rf = z_risk(dcpa, config.distance_high_m, config.distance_low_m)
    rt = z_risk(tcpa, config.time_high_s, config.time_low_s) if tcpa is not None and tcpa >= 0 else 0.
    rp = z_risk(distance, config.distance_high_m, config.distance_low_m)
    risk = (rf + rt + rp)/3
    in_scope = distance <= config.monitor_radius_nm*1852
    by_risk = in_scope and risk >= config.risk_threshold
    by_distance = in_scope and distance <= config.emergency_distance_m
    reason = "综合风险+距离阈值" if by_risk and by_distance else "综合风险阈值" if by_risk else "距离阈值" if by_distance else "未触发"
    cpa = None
    if tcpa is not None and 0 <= tcpa <= 1800:
        cpa = {"own": move(own.latitude,own.longitude,ovx*tcpa,ovy*tcpa),
               "target": move(target.latitude,target.longitude,tvx*tcpa,tvy*tcpa)}
    return {"timestamp": iso(own.timestamp), "time": own.timestamp,
            "own_mmsi": own.mmsi, "target_mmsi": target.mmsi,
            "actual_distance_m": distance, "dcpa_m": dcpa, "tcpa_s": tcpa,
            "risk_dcpa": rf, "risk_tcpa": rt, "risk_distance": rp, "collision_risk": risk,
            "warning_by_risk": by_risk, "warning_by_distance": by_distance,
            "predicted_warning": by_risk or by_distance, "warning_reason": reason,
            "in_scope": in_scope, "data_quality": target.quality, "cpa": cpa,
            "own_latitude": own.latitude, "own_longitude": own.longitude,
            "target_latitude": target.latitude, "target_longitude": target.longitude}


def interpolate_state(a: VesselState, b: VesselState, timestamp: float) -> VesselState:
    """Offline interpolation; interpolate velocity components across 359/0 degrees."""
    q = (timestamp-a.timestamp)/(b.timestamp-a.timestamp) if b.timestamp != a.timestamp else 0
    dx,dy = displacement(a.latitude,a.longitude,b.latitude,b.longitude)
    avx, avy = velocity(a.sog, a.cog)
    bvx, bvy = velocity(b.sog, b.cog)
    vx, vy = avx+(bvx-avx)*q, avy+(bvy-avy)*q
    lat, lon = move(a.latitude,a.longitude,dx*q,dy*q)
    return replace(a, timestamp=timestamp, latitude=lat, longitude=lon,
                   sog=hypot(vx, vy)/KNOT_TO_MPS, cog=degrees(atan2(vx,vy)) % 360,
                   quality="interpolated" if 0 < q < 1 else a.quality)
