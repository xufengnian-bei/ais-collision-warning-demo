"""CSV/NMEA normalization and deterministic offline 1-second reconstruction."""
import bisect
import csv
import io
import math
from datetime import datetime, timezone
from .algorithm import VesselState, KNOT_TO_MPS, displacement, interpolate_state
from .ais import AISDecoder

MAX_RECORDS = 100_000


def parse_timestamp(value):
    value = str(value).strip()
    try:
        ts = float(value)
        return ts / 1000 if ts > 1e12 else ts
    except ValueError:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()


def number(value):
    if value is None or str(value).strip() in ("", "NA", "N/A", "null", "None"):
        return None
    n = float(value)
    return n if math.isfinite(n) else None


def load_tracks(content: bytes, filename: str):
    text = content.decode("utf-8-sig")
    records, errors, duplicates = {}, [], 0
    decoder = AISDecoder()
    if filename.lower().endswith((".nmea", ".txt", ".log")):
        raw_rows = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = decoder.parse(line, require_timestamp=True)
                if row and row["kind"] == "position":
                    raw_rows.append((line_number, row))
            except Exception as exc:
                if len(errors) < 20:
                    errors.append(f"第 {line_number} 行：{exc}")
    elif filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV 没有表头")
        raw_rows = [(i, {str(k).strip().lower():v for k,v in row.items() if k is not None}) for i,row in enumerate(reader,2)]
    else:
        raise ValueError("支持 .csv、.nmea、.txt、.log 文件")
    if len(raw_rows) > MAX_RECORDS:
        raise ValueError("单次导入最多 100000 条位置记录")
    for line_number, row in raw_rows:
        try:
            def get(*keys):
                return next((row[k] for k in keys if k in row and row[k] not in (None,"")), None)
            mmsi = str(get("mmsi")).strip()
            if not mmsi.isdigit() or len(mmsi) != 9:
                raise ValueError("MMSI 必须为 9 位数字")
            ts = parse_timestamp(get("timestamp", "time", "datetime"))
            datetime.fromtimestamp(ts,timezone.utc)
            lat, lon = number(get("latitude","lat")), number(get("longitude","lon"))
            if not math.isfinite(ts) or lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("时间戳或经纬度无效")
            sog, cog = number(get("sog","speed")), number(get("cog","course"))
            if sog is not None and not 0 <= sog < 102.3: sog = None
            if cog is not None and not 0 <= cog < 360: cog = None
            key = (mmsi, ts)
            if key in records: duplicates += 1
            records[key] = {"mmsi":mmsi,"timestamp":ts,"latitude":lat,"longitude":lon,"sog":sog,"cog":cog,
                            "ship_type":int(number(get("ship_type","shiptype")) or 0) or None,
                            "nav_status":int(number(get("nav_status","navigation status")) or 0) if get("nav_status","navigation status") is not None else None,
                            "name":str(get("name","shipname") or mmsi)}
        except Exception as exc:
            if len(errors) < 20: errors.append(f"第 {line_number} 行：{exc}")
    tracks = {}
    for row in sorted(records.values(), key=lambda r:(r["mmsi"],r["timestamp"])):
        tracks.setdefault(row["mmsi"],[]).append(row)
    result, supplemented = {}, 0
    for mmsi, rows in tracks.items():
        states = []
        for i,row in enumerate(rows):
            row = dict(row)
            if row["sog"] is None or row["cog"] is None:
                if len(rows) < 2:
                    errors.append(f"{mmsi} 仅有一个位置点，无法补算速度/航向")
                    continue
                # Use past adjacent pair when possible; future pair only for offline first point.
                a,b = (rows[i-1], rows[i]) if i else (rows[0],rows[1])
                dx,dy = displacement(a["latitude"],a["longitude"],b["latitude"],b["longitude"])
                dt = b["timestamp"]-a["timestamp"]
                speed = math.hypot(dx,dy)/dt/KNOT_TO_MPS
                if speed >= 102.3:
                    errors.append(f"{mmsi} 位置跳变，补算航速超出 AIS 范围")
                    continue
                row["sog"] = speed if row["sog"] is None else row["sog"]
                row["cog"] = math.degrees(math.atan2(dx,dy))%360 if row["cog"] is None else row["cog"]
                row["quality"] = "derived_motion"
                supplemented += 1
            states.append(VesselState(**row))
        if states: result[mmsi] = states
    if len(result) < 2:
        detail = "; ".join(errors[:3])
        raise ValueError("至少需要本船和一艘目标船的有效轨迹。"+detail)
    return result, {"vessels":len(result),"valid_positions":sum(map(len,result.values())),
                    "duplicates_removed":duplicates,"motion_supplemented":supplemented,
                    "issues":errors[:20],"naive_timestamp_timezone":"UTC"}


def state_at(states, timestamp, max_gap=30):
    i = bisect.bisect_left(states, timestamp, key=lambda s:s.timestamp)
    if i < len(states) and abs(states[i].timestamp-timestamp) < .001:
        return states[i]
    if i == 0 or i == len(states): return None
    a,b = states[i-1], states[i]
    if b.timestamp-a.timestamp > max_gap: return None
    return interpolate_state(a,b,timestamp)
