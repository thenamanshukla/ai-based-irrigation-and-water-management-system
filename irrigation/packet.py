"""Radio packet contract between Arduino B (gateway) and the Raspberry Pi.

Arduino B sends one JSON object per line over USB serial, for example:
{"node":"A","ts":"2026-11-05 06:00","moisture":31.2,"soil_temp":24.1,"ec":450,"ph":6.5,
 "n":40,"p":25,"k":120,"rain":0,"tank_cm":7.8,"air_temp":27.4,"air_rh":71,"valve":0}

Units: moisture in % volumetric (as the 7 in 1 probe reports), tank_cm = IR distance
from sensor to water surface in cm, temperatures in deg C, rain and valve 0 or 1.
"node", "ts", "soil_temp", "ec", "ph", "n", "p", "k" are optional; the hub records its own
receive time as the authoritative timestamp.
"""
from __future__ import annotations
import json

REQUIRED = {
    "moisture": (0.0, 100.0),
    "air_temp": (-10.0, 60.0),
    "tank_cm": (0.0, 200.0),
    "rain": (0, 1),
    "valve": (0, 1),
}
OPTIONAL = {
    "air_rh": (0.0, 100.0),
    "soil_temp": (-10.0, 70.0),
    "ec": (0.0, 20000.0),
    "ph": (3.0, 9.0),
    "n": (0.0, 2000.0),
    "p": (0.0, 2000.0),
    "k": (0.0, 2000.0),
}


class PacketError(ValueError):
    pass


def parse(line: str) -> dict:
    """Parse and validate one serial line. Raises PacketError with a clear reason."""
    line = line.strip()
    if not line:
        raise PacketError("empty line")
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as e:
        raise PacketError(f"not JSON: {e.msg}") from None
    if not isinstance(raw, dict):
        raise PacketError("not a JSON object")
    if raw.get("type") not in (None, "reading"):
        raise PacketError(f"not a reading (type={raw.get('type')})")

    out = {"node": str(raw.get("node", "A"))[:8], "node_ts": str(raw.get("ts", ""))[:19]}
    for key, (lo, hi) in REQUIRED.items():
        if key not in raw:
            raise PacketError(f"missing '{key}'")
        out[key] = _number(key, raw[key], lo, hi)
    for key, (lo, hi) in OPTIONAL.items():
        out[key] = _number(key, raw[key], lo, hi) if raw.get(key) is not None else None
    out["rain"] = int(out["rain"])
    out["valve"] = int(out["valve"])
    return out


def _number(key, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PacketError(f"'{key}' is not a number")
    if value != value:  # NaN
        raise PacketError(f"'{key}' is NaN")
    if not lo <= value <= hi:
        raise PacketError(f"'{key}'={value} outside {lo}..{hi}")
    return float(value)


def valve_command(minutes: float, command_id: str) -> str:
    """Line sent from the Pi to Arduino B, which relays it to the field node."""
    return json.dumps({"cmd": "valve", "minutes": round(float(minutes), 1), "id": command_id}) + "\n"
