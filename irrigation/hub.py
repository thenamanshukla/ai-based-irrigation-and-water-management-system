"""Real-time hub: receives serial lines, stores real readings, decides on the wall clock,
watches tank drawdown for leaks and clogs, and sends valve commands to the field.

Nothing here generates data. If no packets arrive, the database stays empty and no
decision is made."""
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timedelta

from . import models as M
from .packet import parse, PacketError, valve_command
from .planner import plan, DailyInputs

log = logging.getLogger("hub")
TS = "%Y-%m-%d %H:%M:%S"


class Hub:
    def __init__(self, cfg, store, send_line=None, now_fn=datetime.now, stress_fn=None):
        if not cfg.service.planting_date:
            raise ValueError("Set service.planting_date (YYYY-MM-DD) in settings.json before starting.")
        self.cfg = cfg
        self.store = store
        self.send_line = send_line or (lambda line: None)
        self.now = now_fn
        self.stress_fn = stress_fn or (lambda: None)        # IMX500 result; None until the camera is set up
        self.planting = datetime.strptime(cfg.service.planting_date, "%Y-%m-%d")
        h, m = cfg.service.plan_time.split(":")
        self.plan_hm = (int(h), int(m))

        self.detector = M.FaultDetector(cfg)
        self.detector.load_state(store.get_state("fault_detector"))
        self.window = deque(maxlen=7)                        # (time, tank depth) while the valve is open
        self.event_status = None
        self.last_attempt = None

    # ================================================================ input
    def handle_line(self, line: str):
        """One line from Arduino B. Valid readings are stored; anything else is logged and kept for audit."""
        now = self.now()
        try:
            r = parse(line)
        except PacketError as e:
            self.store.add_rejected(now.strftime(TS), str(e), line)
            log.warning("rejected packet: %s | %s", e, line.strip()[:120])
            return None
        r["ts"] = now.strftime(TS)
        self.store.add_reading(r)
        self._watch_flow(r, now)
        if self.store.get_state("field_offline"):
            self.store.set_state("field_offline", False)
            self.store.add_alert(r["ts"], "field_online", "Field node is sending data again.")
        self._write_status()
        return r

    # ================================================================ called every second
    def tick(self):
        now = self.now()
        self._check_field_alive(now)
        self._check_manual_request(now)
        plan_at = now.replace(hour=self.plan_hm[0], minute=self.plan_hm[1], second=0, microsecond=0)
        today = now.strftime("%Y-%m-%d")
        if now >= plan_at and not self.store.has_decision(today):
            if self.last_attempt is None or now - self.last_attempt >= timedelta(minutes=15):
                self.last_attempt = now
                self._daily_plan(now)

    # ================================================================ Eq. (6): leaks and clogs
    def _depth(self, r):
        return M.tank_depth_from_ir(r["tank_cm"] / 100, self.cfg.tank)

    def _watch_flow(self, r, now):
        if not r["valve"]:
            self.window.clear()
            if self.event_status is not None:
                self.store.set_state("pipe_status", self.event_status)
            self.event_status = None
            self.detector.reset_streaks()
            return
        self.window.append((now, self._depth(r)))
        if len(self.window) < self.window.maxlen:
            return
        (t0, d0), (t1, d1) = self.window[0], self.window[-1]
        hours = (t1 - t0).total_seconds() / 3600
        if hours <= 0:
            return
        q_obs = (d0 - d1) * self.cfg.tank_area_m2 * 1000 / hours
        head = M.head_m((d0 + d1) / 2, self.cfg.tank)
        status = self.detector.update(q_obs, head)
        self.store.set_state("fault_detector", self.detector.to_state())
        if status == "learning":
            return
        if self.event_status in (None, "normal"):
            self.event_status = status
            if status in ("leak", "clog"):
                msg = ("Tank is emptying faster than the drippers can explain: possible leak."
                       if status == "leak" else
                       "Tank is emptying slower than expected: drippers or filter may be clogged.")
                self.store.add_alert(now.strftime(TS), status, msg)
                log.warning(msg)

    # ================================================================ daily decision
    def _daily_plan(self, now):
        latest = self.store.latest()
        if latest is None:
            self._skip(now, "no readings received from the field yet")
            return
        age_min = (now - datetime.strptime(latest["ts"], TS)).total_seconds() / 60
        if age_min > self.cfg.rules.max_reading_age_min:
            self._skip(now, f"latest reading is {age_min:.0f} min old")
            return
        start = (now - timedelta(hours=24)).strftime(TS)
        tmax, tmin, n = self.store.db.execute(
            "SELECT MAX(air_temp), MIN(air_temp), COUNT(*) FROM readings WHERE ts >= ? AND ts <= ?",
            (start, now.strftime(TS))).fetchone()
        if n < self.cfg.rules.min_readings_per_day:
            self._skip(now, f"only {n} readings in the last 24 h (need {self.cfg.rules.min_readings_per_day})")
            return

        doy = (now - timedelta(days=1)).timetuple().tm_yday
        et0 = M.et0_hargreaves(tmax, tmin, self.cfg.site.latitude_deg, doy)
        hist = (self.store.get_state("et0_history", []) + [round(et0, 3)])[-7:]
        self.store.set_state("et0_history", hist)

        x = DailyInputs(
            day_of_year=doy, day_after_planting=max(1, (now - self.planting).days + 1),
            t_max=tmax, t_min=tmin, theta=latest["moisture"] / 100, raining=bool(latest["rain"]),
            tank_depth_m=self._depth(latest), pond_l=self.pond_l(),
            stress_prob=self.stress_fn(), recent_et0=hist)
        d = plan(self.cfg, x).to_dict()
        d["pipe_status"] = self.store.get_state("pipe_status", "not yet checked")
        d["readings_used"] = n
        d["camera"] = "available" if x.stress_prob is not None else "not connected"
        d["pond_l_source"] = "farmer entry" if self.store.get_state("pond_l") is not None else "not set (assumed 0)"
        self.store.add_decision(now.strftime("%Y-%m-%d"), now.strftime(TS), d)
        log.info("decision %s: %s %s min, reasons: %s", now.date(), d["action"], d["minutes"], d["reasons"])
        if d["action"] == "water":
            self._send_valve(now, d["minutes"], "planner")
        self._write_status()

    def _skip(self, now, reason):
        log.warning("no decision yet: %s (will retry in 15 min)", reason)
        key = "skip_alerted_" + now.strftime("%Y-%m-%d")
        if not self.store.get_state(key):
            self.store.set_state(key, True)
            self.store.add_alert(now.strftime(TS), "no_decision", f"Daily plan postponed: {reason}.")

    # ================================================================ valve commands
    def _send_valve(self, now, minutes, source):
        cid = uuid.uuid4().hex[:8]
        try:
            self.send_line(valve_command(minutes, cid))
        except Exception as e:                                   # serial unplugged
            self.store.add_alert(now.strftime(TS), "command_failed", f"Could not send valve command: {e}")
            log.error("valve command failed: %s", e)
            return False
        self.store.add_command(cid, now.strftime(TS), minutes, source)
        log.info("valve command %s: %.1f min (%s)", cid, minutes, source)
        return True

    def _check_manual_request(self, now):
        """Farmer request written by the CLI or the web app. Hard safety rules still apply."""
        req = self.store.get_state("manual_request")
        if not req:
            return
        self.store.set_state("manual_request", None)
        latest = self.store.latest()
        minutes = float(req.get("minutes", 0))
        reasons = []
        if latest is None:
            reasons.append("no field data")
        else:
            storage = M.tank_volume_l(self._depth(latest), self.cfg.tank_area_m2) + self.pond_l()
            if latest["rain"]:
                reasons.append("raining")
            if storage <= self.cfg.tank.reserve_l:
                reasons.append("storage at reserve")
            if latest["moisture"] / 100 >= self.cfg.soil.theta_fc:
                reasons.append("soil already at field capacity")
        if not 0 < minutes <= self.cfg.rules.max_valve_min:
            reasons.append(f"minutes must be between 0 and {self.cfg.rules.max_valve_min:.0f}")
        if reasons:
            self.store.add_alert(now.strftime(TS), "manual_blocked", "Manual watering refused: " + ", ".join(reasons))
        else:
            self._send_valve(now, minutes, "manual")

    # ================================================================ health
    def _check_field_alive(self, now):
        latest = self.store.latest()
        if latest is None or self.store.get_state("field_offline"):
            return
        age = (now - datetime.strptime(latest["ts"], TS)).total_seconds() / 60
        if age > self.cfg.rules.hub_timeout_min:
            self.store.set_state("field_offline", True)
            self.store.add_alert(now.strftime(TS), "field_offline",
                                 f"No data from the field node for {age:.0f} minutes.")
            log.error("field node silent for %.0f min", age)

    # ================================================================ helpers
    def pond_l(self) -> float:
        v = self.store.get_state("pond_l")
        return float(v) if v is not None else 0.0

    def status(self) -> dict:
        latest = self.store.latest()
        today = self.store.decision(self.now().strftime("%Y-%m-%d"))
        s = {"updated": self.now().strftime(TS), "field": None, "today": today,
             "pipe_status": self.store.get_state("pipe_status", "not yet checked"),
             "field_online": not self.store.get_state("field_offline", False),
             "alerts": [dict(ts=a, kind=k, message=m) for a, k, m in self.store.recent_alerts(5)]}
        if latest:
            tank_l = M.tank_volume_l(self._depth(latest), self.cfg.tank_area_m2)
            s["field"] = {"time": latest["ts"], "soil_moisture_pct": latest["moisture"],
                          "air_temp_c": latest["air_temp"], "raining": bool(latest["rain"]),
                          "tank_l": round(tank_l, 1), "pond_l": self.pond_l(),
                          "valve": "open" if latest["valve"] else "closed"}
        return s

    def _write_status(self):
        path = self.cfg.service.status_path
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.status(), f, indent=2)
        os.replace(tmp, path)                                   # atomic: the app never reads half a file
