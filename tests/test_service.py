"""End-to-end tests of the real-time path, using a temporary database and a fake clock.
The simulator feeds the real Hub exactly as Arduino B would; nothing touches data/."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

from irrigation import config
from irrigation.hub import Hub
from irrigation.packet import parse, PacketError
from irrigation.store import Store
from tests.sim_field import FieldSim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = {"moisture": 28.5, "air_temp": 29.0, "tank_cm": 8.0, "rain": 0, "valve": 0, "air_rh": 70}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp, start, **service):
    cfg = config.Config()
    cfg.service.planting_date = start.strftime("%Y-%m-%d")
    cfg.service.status_path = os.path.join(tmp, "status.json")
    for k, v in service.items():
        setattr(cfg.service, k, v)
    store = Store(os.path.join(tmp, "test.sqlite"))
    clock = Clock(start)
    sent = []
    hub = Hub(cfg, store, send_line=sent.append, now_fn=clock)
    return cfg, store, hub, clock, sent


def line(**kw):
    return json.dumps({**GOOD, **kw})


class TestPacket(unittest.TestCase):
    def test_valid(self):
        r = parse(line())
        self.assertEqual(r["moisture"], 28.5)
        self.assertIsNone(r["ph"])

    def test_rejections(self):
        for bad, why in [("", "empty"), ("hello", "JSON"), ("[1,2]", "object"),
                         (json.dumps({**GOOD, "moisture": 140}), "outside"),
                         (json.dumps({k: v for k, v in GOOD.items() if k != "tank_cm"}), "missing"),
                         (json.dumps({**GOOD, "air_temp": "hot"}), "not a number"),
                         (json.dumps({**GOOD, "type": "debug"}), "not a reading")]:
            with self.assertRaises(PacketError) as cm:
                parse(bad)
            self.assertIn(why, str(cm.exception))


class TestHubRealTime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.start = datetime(2026, 11, 5, 0, 0)

    def test_fresh_database_is_empty(self):
        _, store, hub, _, _ = make(self.tmp, self.start)
        self.assertEqual(store.counts(), {"readings": 0, "decisions": 0, "commands": 0, "alerts": 0, "rejected": 0})
        self.assertIsNone(hub.status()["field"])

    def test_requires_planting_date(self):
        cfg = config.Config()
        with self.assertRaises(ValueError):
            Hub(cfg, Store(":memory:"))

    def test_store_uses_hub_clock_and_rejects_bad(self):
        _, store, hub, clock, _ = make(self.tmp, self.start)
        clock.t = datetime(2026, 11, 5, 10, 15, 30)
        hub.handle_line(line(ts="1999-01-01 00:00"))       # wrong RTC on the field node
        hub.handle_line("garbage")
        self.assertEqual(store.latest()["ts"], "2026-11-05 10:15:30")
        self.assertEqual(store.latest()["node_ts"], "1999-01-01 00:00")
        self.assertEqual(store.counts()["rejected"], 1)

    def test_no_plan_without_enough_data_then_alert_once(self):
        _, store, hub, clock, _ = make(self.tmp, self.start)
        clock.t = datetime(2026, 11, 5, 6, 0)
        hub.handle_line(line())
        for m in range(0, 60, 5):
            clock.t = datetime(2026, 11, 5, 6, m)
            hub.tick()
        self.assertEqual(store.counts()["decisions"], 0)
        kinds = [k for _, k, _ in store.recent_alerts()]
        self.assertEqual(kinds.count("no_decision"), 1)

    def feed_day(self, hub, clock, day, **kw):
        t = day
        while t < day + timedelta(days=1):
            clock.t = t
            hub.handle_line(line(air_temp=22 + 10 * (t.hour >= 12), **kw))
            hub.tick()
            t += timedelta(minutes=5)

    def test_one_decision_per_day_at_plan_time_and_valve_sent(self):
        _, store, hub, clock, sent = make(self.tmp, self.start)
        self.feed_day(hub, clock, self.start, moisture=19.0)          # dry soil all day
        decisions = store.db.execute("SELECT date, ts FROM decisions").fetchall()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0][1][11:16], "06:00")
        d = store.decision("2026-11-05")
        self.assertEqual(d["action"], "water")
        self.assertEqual(len(sent), 1)
        self.assertEqual(json.loads(sent[0])["cmd"], "valve")
        self.assertEqual(store.counts()["commands"], 1)

    def test_rain_blocks(self):
        _, store, hub, clock, sent = make(self.tmp, self.start)
        self.feed_day(hub, clock, self.start, moisture=19.0, rain=1)
        self.assertEqual(store.decision("2026-11-05")["action"], "blocked")
        self.assertEqual(sent, [])

    def test_field_offline_and_back(self):
        _, store, hub, clock, _ = make(self.tmp, self.start)
        clock.t = datetime(2026, 11, 5, 1, 0)
        hub.handle_line(line())
        clock.t = datetime(2026, 11, 5, 1, 40)
        hub.tick()
        clock.t = datetime(2026, 11, 5, 1, 45)
        hub.handle_line(line())
        kinds = [k for _, k, _ in reversed(store.recent_alerts())]
        self.assertEqual(kinds, ["field_offline", "field_online"])

    def test_manual_request(self):
        _, store, hub, clock, sent = make(self.tmp, self.start)
        clock.t = datetime(2026, 11, 5, 9, 0)
        hub.handle_line(line(rain=1))
        store.set_state("manual_request", {"minutes": 10})
        hub.tick()
        self.assertEqual(sent, [])
        hub.handle_line(line(rain=0))
        store.set_state("manual_request", {"minutes": 10})
        hub.tick()
        self.assertEqual(len(sent), 1)

    def test_calibration_survives_restart(self):
        cfg, store, hub, clock, _ = make(self.tmp, self.start)
        hub.detector._calib = [0.1] * 12
        hub.detector.state.calibrated = True
        store.set_state("fault_detector", hub.detector.to_state())
        hub2 = Hub(cfg, store, now_fn=clock)
        self.assertTrue(hub2.detector.state.calibrated)


class TestSeasonThroughRealHub(unittest.TestCase):
    def test_45_days_with_faults(self):
        tmp = tempfile.mkdtemp()
        start = datetime(2026, 11, 5)
        faults = {"clog": (20, 30, 0.55), "leak": (32, 44, 2.0)}
        _, store, hub, clock, sent = make(tmp, start)
        sim = FieldSim(hub.cfg, start, seed=11, faults=faults)
        hub.send_line = lambda l: (sent.append(l), sim.command_valve(json.loads(l)["minutes"]))
        store.set_state("pond_l", sim.pond_l)
        for _ in range(45 * 288):
            clock.t = sim.t
            p = sim.step()
            p.pop("ts")
            hub.handle_line(json.dumps(p))
            hub.tick()
        c = store.counts()
        self.assertEqual(c["rejected"], 0)
        self.assertGreaterEqual(c["decisions"], 44)
        self.assertGreater(c["commands"], 0)
        alerts = {(t[:10], k) for t, k, _ in store.recent_alerts(200) if k in ("leak", "clog")}
        for date, kind in alerts:
            day = (datetime.strptime(date, "%Y-%m-%d") - start).days
            s, e, _ = faults[kind]
            self.assertTrue(s <= day < e, f"false {kind} alert on day {day}")
        self.assertTrue(alerts, "no faults detected")


class TestServiceProcess(unittest.TestCase):
    def test_bench_mode_writes_only_what_is_typed(self):
        tmp = tempfile.mkdtemp()
        settings = os.path.join(tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"service": {"planting_date": "2026-11-01", "db_path": os.path.join(tmp, "db.sqlite"),
                                   "status_path": os.path.join(tmp, "status.json"),
                                   "log_path": os.path.join(tmp, "hub.log")}}, f)
        stdin = line() + "\n" + "not json\n" + line(moisture=30.1) + "\n"
        r = subprocess.run([sys.executable, "-m", "irrigation.service", "--stdin", "--settings", settings],
                           input=stdin, capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        c = Store(os.path.join(tmp, "db.sqlite")).counts()
        self.assertEqual((c["readings"], c["rejected"]), (2, 1))
        status = json.load(open(os.path.join(tmp, "status.json")))
        self.assertEqual(status["field"]["soil_moisture_pct"], 30.1)

    def test_refuses_to_start_without_planting_date(self):
        tmp = tempfile.mkdtemp()
        settings = os.path.join(tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"service": {"db_path": os.path.join(tmp, "db.sqlite"),
                                   "log_path": os.path.join(tmp, "hub.log")}}, f)
        r = subprocess.run([sys.executable, "-m", "irrigation.service", "--stdin", "--settings", settings],
                           input="", capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
