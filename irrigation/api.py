"""HTTP API for the phone app. Runs on the Pi next to the hub service and reads the same database.

    python -m irrigation.api                 # listens on 0.0.0.0:8080 (service.api_port)

Endpoints (all JSON):
    GET  /api/health                  name, version, whether a PIN is required
    GET  /api/status                  latest field data, today's decision, pipe status, recent alerts
    GET  /api/history?hours=48        readings for charts (max 300 points)
    GET  /api/decisions?days=14       daily decisions, newest first
    GET  /api/alerts?n=30             alerts, newest first
    POST /api/water   {"minutes": 15, "pin": "1234"}   manual watering request (safety rules still apply)
    POST /api/pond    {"litres": 120, "pin": "1234"}   pond level entered by the farmer
    POST /api/ask     {"question": "...", "lang": "hi"}  Llama 3.2 1B on the Pi's Arm CPU (ExecuTorch)

Only the standard library is used, so nothing extra needs installing on the Pi.
"""
from __future__ import annotations
import argparse
import hmac
import json
import logging
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import assistant, config, models as M
from .hub import Hub, TS
from .store import Store

VERSION = "1.0"
log = logging.getLogger("api")


class Api:
    def __init__(self, cfg):
        self.cfg = cfg
        self.store = Store(cfg.service.db_path, shared=True)
        self.lock = threading.Lock()           # one request touches the database at a time
        self.hub = Hub(cfg, self.store)        # used only for read helpers; never talks to the field

    # ------------------------------------------------------------ reads
    def health(self):
        return {"ok": True, "name": self.cfg.service.farm_name, "version": VERSION,
                "pin_required": bool(self.cfg.service.app_pin), "time": datetime.now().strftime(TS),
                "assistant": assistant.installed(self.cfg.service.llm_dir)}

    def status(self):
        s = self.hub.status()
        s["farm_name"] = self.cfg.service.farm_name
        s["tank_capacity_l"] = self.cfg.tank.capacity_l
        s["counts"] = self.store.counts()
        s["manual_pending"] = bool(self.store.get_state("manual_request"))
        last_cmd = self.store.db.execute("SELECT ts, minutes, source FROM commands ORDER BY ts DESC LIMIT 1").fetchone()
        s["last_watering"] = dict(zip(("ts", "minutes", "source"), last_cmd)) if last_cmd else None
        if s.get("field"):
            age = (datetime.now() - datetime.strptime(s["field"]["time"], TS)).total_seconds() / 60
            s["field"]["age_min"] = round(age, 1)
        return s

    def history(self, hours):
        hours = max(1, min(int(hours), 24 * 31))
        since = (datetime.now() - timedelta(hours=hours)).strftime(TS)
        rows = self.store.db.execute(
            "SELECT ts, moisture, tank_cm, air_temp, rain, valve FROM readings WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
        step = max(1, len(rows) // 300)
        out = []
        for ts, moist, tank_cm, air, rain, valve in rows[::step]:
            depth = M.tank_depth_from_ir(tank_cm / 100, self.cfg.tank) if tank_cm is not None else None
            out.append({"ts": ts, "moisture": moist, "air_temp": air, "rain": rain, "valve": valve,
                        "tank_l": round(M.tank_volume_l(depth, self.cfg.tank_area_m2), 1) if depth is not None else None})
        return {"hours": hours, "points": out, "field_capacity_pct": self.cfg.soil.theta_fc * 100,
                "trigger_pct": round(100 * (self.cfg.soil.theta_fc - self.cfg.crop.depletion_fraction_p *
                                            (self.cfg.soil.theta_fc - self.cfg.soil.theta_wp)), 1)}

    def decisions(self, days):
        rows = self.store.db.execute("SELECT date, ts, payload FROM decisions ORDER BY date DESC LIMIT ?",
                                     (max(1, min(int(days), 366)),)).fetchall()
        return {"decisions": [dict(date=d, ts=t, **json.loads(p)) for d, t, p in rows]}

    def alerts(self, n):
        rows = self.store.db.execute("SELECT ts, kind, message FROM alerts ORDER BY id DESC LIMIT ?",
                                     (max(1, min(int(n), 200)),)).fetchall()
        return {"alerts": [dict(ts=t, kind=k, message=m) for t, k, m in rows]}

    # ------------------------------------------------------------ writes
    def check_pin(self, body):
        pin = self.cfg.service.app_pin
        return not pin or hmac.compare_digest(str(body.get("pin", "")), pin)

    def water(self, body):
        if not self.check_pin(body):
            return 403, {"ok": False, "error": "wrong_pin"}
        try:
            minutes = float(body.get("minutes"))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "minutes_required"}
        if not 0 < minutes <= self.cfg.rules.max_valve_min:
            return 400, {"ok": False, "error": "minutes_range", "max": self.cfg.rules.max_valve_min}
        self.store.set_state("manual_request", {"minutes": minutes, "ts": datetime.now().strftime(TS)})
        return 200, {"ok": True, "queued_minutes": minutes}

    def pond(self, body):
        if not self.check_pin(body):
            return 403, {"ok": False, "error": "wrong_pin"}
        try:
            litres = float(body.get("litres"))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "litres_required"}
        if not 0 <= litres <= 1e7:
            return 400, {"ok": False, "error": "litres_range"}
        self.store.set_state("pond_l", litres)
        return 200, {"ok": True, "pond_l": litres}


    def ask(self, body):
        q = str(body.get("question", "")).strip()
        if not q or len(q) > 500:
            return 400, {"ok": False, "error": "question_required"}
        sv = self.cfg.service
        if not assistant.installed(sv.llm_dir):
            return 503, {"ok": False, "error": "assistant_not_installed"}
        with self.lock:                          # read the facts, then free the database for other requests
            fact_text = assistant.facts(self.hub.status(), self.cfg.tank.capacity_l)
        lang = "hi" if body.get("lang") == "hi" else "en"
        out = assistant.ask(q, lang, fact_text, sv.llm_dir, sv.llm_threads, sv.llm_max_new_tokens)
        log.info("ask (%s) %.1fs %s", lang, out["seconds"], out.get("speed"))
        return 200, dict(ok=True, **out)


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IrrigationHub/" + VERSION

        def _send(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")        # app runs from its own origin
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self._send(204, {})

        def do_GET(self):
            with api.lock:
                self._get()

        def do_POST(self):
            if urlparse(self.path).path == "/api/ask":    # slow; must not hold the database lock
                return self._post()
            with api.lock:
                self._post()

        def _get(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/health":
                    return self._send(200, api.health())
                if u.path == "/api/status":
                    return self._send(200, api.status())
                if u.path == "/api/history":
                    return self._send(200, api.history(q.get("hours", 48)))
                if u.path == "/api/decisions":
                    return self._send(200, api.decisions(q.get("days", 14)))
                if u.path == "/api/alerts":
                    return self._send(200, api.alerts(q.get("n", 30)))
                self._send(404, {"ok": False, "error": "not_found"})
            except ValueError:
                self._send(400, {"ok": False, "error": "bad_parameter"})
            except Exception as e:
                log.exception("GET %s failed", u.path)
                self._send(500, {"ok": False, "error": "server_error", "detail": str(e)})

        def _post(self):
            u = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 4096:
                    return self._send(413, {"ok": False, "error": "too_large"})
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"ok": False, "error": "bad_json"})
            try:
                if u.path == "/api/water":
                    return self._send(*api.water(body))
                if u.path == "/api/pond":
                    return self._send(*api.pond(body))
                if u.path == "/api/ask":
                    return self._send(*api.ask(body))
                self._send(404, {"ok": False, "error": "not_found"})
            except Exception as e:
                log.exception("POST %s failed", u.path)
                self._send(500, {"ok": False, "error": "server_error", "detail": str(e)})

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Irrigation API for the phone app")
    ap.add_argument("--settings", default="settings.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int)
    a = ap.parse_args(argv)
    cfg = config.load(a.settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    api = Api(cfg)
    port = a.port or cfg.service.api_port
    srv = ThreadingHTTPServer((a.host, port), make_handler(api))
    log.info("API on http://%s:%d (PIN %s)", a.host, port, "required" if cfg.service.app_pin else "not set")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
