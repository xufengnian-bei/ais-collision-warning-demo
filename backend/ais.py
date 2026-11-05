"""Standard NMEA UDP transport, optional checksummed NMEA tag-block timestamps."""
import asyncio
import re
import time
from datetime import datetime, timezone
from pyais import decode
from pyais.encode import encode_dict
from .algorithm import VesselState


def checksum(text: str) -> str:
    value = 0
    for char in text:
        value ^= ord(char)
    return f"{value:02X}"


def tagged(sentence: str, timestamp: float) -> str:
    body = f"s:AIS-DEMO,c:{timestamp:.3f}"
    return f"\\{body}*{checksum(body)}\\{sentence}"


def encode_position(state: VesselState, ais_class="A", own=False):
    payload = {"type": 1 if ais_class == "A" else 18, "mmsi": int(state.mmsi),
               "lat": state.latitude, "lon": state.longitude, "speed": state.sog,
               "course": state.cog, "heading": 511, "second": int(state.timestamp) % 60}
    if ais_class == "A":
        payload["status"] = state.nav_status if state.nav_status is not None else 15
    return [tagged(s, state.timestamp) for s in encode_dict(payload, radio_channel="A", talker_id="AI", sentence_type="VDO" if own else "VDM")]


def encode_static(state: VesselState, ais_class="A"):
    payload = {"type": 5 if ais_class == "A" else 24, "mmsi": int(state.mmsi),
               "shipname": f"DEMO {state.mmsi[-3:]}", "ship_type": state.ship_type or 0}
    messages = []
    if ais_class == "A":
        messages.extend(encode_dict(payload, sentence_type="VDM"))
    else:
        messages.extend(encode_dict({**payload, "partno": 0}, sentence_type="VDM"))
        messages.extend(encode_dict({**payload, "partno": 1}, sentence_type="VDM"))
    return [tagged(s, state.timestamp) for s in messages]


class AISDecoder:
    def __init__(self):
        self.fragments = {}
        self.metadata = {}

    def parse(self, raw: str, peer="file", require_timestamp=False):
        line = raw.strip()
        timestamp, has_timestamp = time.time(), False
        if line.startswith("\\"):
            tag, line = line[1:].split("\\", 1)
            body, expected = tag.rsplit("*", 1)
            if checksum(body) != expected.upper():
                raise ValueError("NMEA tag block 校验失败")
            match = re.search(r"(?:^|,)c:([\d.]+)", body)
            if match:
                timestamp, has_timestamp = float(match[1]), True
                # Reject malformed or unrepresentable epoch values at the boundary.
                datetime.fromtimestamp(timestamp,timezone.utc)
        if require_timestamp and not has_timestamp:
            raise ValueError("NMEA 回放需要包含完整时间戳的 c: tag block；也可导入带 timestamp 的 CSV")
        body, expected = line[1:].rsplit("*", 1)
        if not line.startswith(("!AIVDM,", "!AIVDO,")) or checksum(body) != expected.upper():
            raise ValueError("AIS 报文格式或校验和错误")
        parts = line.split(",")
        total, number = int(parts[1]), int(parts[2])
        if not 1 <= number <= total <= 9:
            raise ValueError("AIS 分片编号无效")
        # Remove abandoned groups; incoming packets never create an unbounded buffer.
        now = time.monotonic()
        self.fragments = {k:v for k,v in self.fragments.items() if now-v[0] < 10}
        if total > 1:
            key = (peer, parts[0], parts[3], parts[4], total)
            _, group = self.fragments.setdefault(key, (now, {}))
            group[number] = line
            if len(group) != total:
                return None
            lines = [group[i] for i in range(1, total+1)]
            del self.fragments[key]
        else:
            lines = [line]
        msg = decode(*lines).asdict()
        mmsi = str(msg["mmsi"]).zfill(9)
        metadata = self.metadata.setdefault(mmsi, {})
        for field in ("ship_type", "shipname"):
            if msg.get(field):
                metadata[field] = msg[field]
        if msg["msg_type"] not in (1, 2, 3, 18, 19):
            return {"kind": "static", "mmsi": mmsi}
        lat, lon, sog, cog = msg.get("lat"), msg.get("lon"), msg.get("speed"), msg.get("course")
        if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("AIS 位置不可用")
        # Speed/course N/A need two measured positions. Do not turn sentinels into valid motion.
        return {"kind": "position", "mmsi": mmsi, "timestamp": timestamp,
                "latitude": lat, "longitude": lon,
                "sog": sog if sog is not None and 0 <= sog < 102.3 else None,
                "cog": cog if cog is not None and 0 <= cog < 360 else None,
                "nav_status": msg.get("status"), "ship_type": metadata.get("ship_type"),
                "name": metadata.get("shipname", ""), "has_full_timestamp": has_timestamp}


class UDPReceiver(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self.callback = callback

    def datagram_received(self, data, addr):
        for line in data.decode("ascii", errors="replace").splitlines():
            if line.strip():
                self.callback(line, addr)
