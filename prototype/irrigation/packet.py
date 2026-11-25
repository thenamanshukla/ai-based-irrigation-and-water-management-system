"""Serial packet contract between the Arduino UNO field controller and the Raspberry Pi.

The UNO sends one JSON object per line over USB serial (115200 baud), for example:
{"node":"UNO","ts":"2026-11-25 10:00:00","moisture":36.2,"soil_temp":24.1,"ec":450,"ph":6.5,
 "n":40,"p":25,"k":120,"moisture2":41.0,"air_temp":27.0,"air_rh":71.0,"mq135":312,
 "ir_object":0,"valve":0,"mode":"pi","sd":1}

moisture  = 7 in 1 probe at 7 cm (% volumetric), the reading used for decisions
moisture2 = resistive soil sensor at 4.5 cm (%), shown alongside
mq135     = MQ135 gas sensor, raw ADC 0 to 1023 (air quality indicator)
ir_object = IR obstacle sensor, 1 when something is in front of it
rain, tank_cm are accepted for rigs that have a rain sensor or a tank level sensor.
Lines with "type" other than "reading" (ack, boot) are status messages, not readings.
The hub records its own receive time as the authoritative timestamp.
"""
from __future__ import annotations
import json

REQUIRED = {
    "valve": (0, 1),
}
OPTIONAL = {
    "moisture": (0.0, 100.0),
    "moisture2": (0.0, 100.0),
    "air_temp": (-10.0, 60.0),
    "mq135": (0.0, 1023.0),
    "ir_object": (0, 1),
    "rain": (0, 1),
    "tank_cm": (0.0, 200.0),
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


class StatusMessage(Exception):
    """A valid non-reading line from the UNO (command acknowledgement, boot notice)."""
    def __init__(self, msg: dict):
        super().__init__(msg.get("type"))
        self.msg = msg


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
    if raw.get("type") in ("ack", "boot"):
        raise StatusMessage(raw)
    if raw.get("type") not in (None, "reading"):
        raise PacketError(f"not a reading (type={raw.get('type')})")

    out = {"node": str(raw.get("node", "A"))[:8], "node_ts": str(raw.get("ts", ""))[:19]}
    for key, (lo, hi) in REQUIRED.items():
        if key not in raw:
            raise PacketError(f"missing '{key}'")
        out[key] = _number(key, raw[key], lo, hi)
    for key, (lo, hi) in OPTIONAL.items():
        out[key] = _number(key, raw[key], lo, hi) if raw.get(key) is not None else None
    if out["moisture"] is None and out["moisture2"] is None:
        raise PacketError("no soil moisture reading")
    for key in ("valve", "rain", "ir_object"):
        if out[key] is not None:
            out[key] = int(out[key])
    out["mode"] = str(raw.get("mode", ""))[:8]
    return out


def soil_pct(r: dict):
    """Moisture used for decisions: the 7 in 1 probe, or the resistive sensor if the probe failed."""
    return r["moisture"] if r.get("moisture") is not None else r.get("moisture2")


def _number(key, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PacketError(f"'{key}' is not a number")
    if value != value:  # NaN
        raise PacketError(f"'{key}' is NaN")
    if not lo <= value <= hi:
        raise PacketError(f"'{key}'={value} outside {lo}..{hi}")
    return float(value)


def valve_command(minutes: float, command_id: str) -> str:
    """Line sent from the Pi to the UNO. minutes = 0 closes the valve."""
    return json.dumps({"cmd": "valve", "minutes": round(float(minutes), 1), "id": command_id}) + "\n"


def time_command(now_text: str) -> str:
    """Sets the UNO's RTC from the Pi clock."""
    return json.dumps({"cmd": "time", "t": now_text}) + "\n"
