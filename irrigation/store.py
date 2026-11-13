"""SQLite storage. The database starts empty and is filled only by real packets."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,            -- hub receive time, local, YYYY-MM-DD HH:MM:SS
  node TEXT, node_ts TEXT,
  moisture REAL, soil_temp REAL, ec REAL, ph REAL, n REAL, p REAL, k REAL,
  rain INTEGER, tank_cm REAL, air_temp REAL, air_rh REAL, valve INTEGER);
CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS decisions (date TEXT PRIMARY KEY, ts TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, ts TEXT, minutes REAL, source TEXT);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS rejected (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, reason TEXT, line TEXT);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""

FIELDS = ["ts", "node", "node_ts", "moisture", "soil_temp", "ec", "ph", "n", "p", "k",
          "rain", "tank_cm", "air_temp", "air_rh", "valve"]


class Store:
    def __init__(self, path: str, shared: bool = False):
        """shared=True lets several threads use the connection; the caller must serialise access."""
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=not shared, timeout=5)
        self.db.executescript(SCHEMA)

    # -------- writes (each commits, so nothing is lost on power cut)
    def add_reading(self, r: dict):
        self.db.execute(f"INSERT INTO readings ({','.join(FIELDS)}) VALUES ({','.join('?' * len(FIELDS))})",
                        [r.get(f) for f in FIELDS])
        self.db.commit()

    def add_rejected(self, ts: str, reason: str, line: str):
        self.db.execute("INSERT INTO rejected (ts, reason, line) VALUES (?, ?, ?)", (ts, reason, line[:500]))
        self.db.commit()

    def add_decision(self, date: str, ts: str, payload: dict):
        self.db.execute("INSERT OR REPLACE INTO decisions VALUES (?, ?, ?)", (date, ts, json.dumps(payload)))
        self.db.commit()

    def add_command(self, cid: str, ts: str, minutes: float, source: str):
        self.db.execute("INSERT INTO commands VALUES (?, ?, ?, ?)", (cid, ts, minutes, source))
        self.db.commit()

    def add_alert(self, ts: str, kind: str, message: str):
        self.db.execute("INSERT INTO alerts (ts, kind, message) VALUES (?, ?, ?)", (ts, kind, message))
        self.db.commit()

    def set_state(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))
        self.db.commit()

    # -------- reads
    def get_state(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def day_air(self, date: str):
        """(max, min, count) of air temperature for one local date."""
        return self.db.execute("SELECT MAX(air_temp), MIN(air_temp), COUNT(*) FROM readings WHERE ts LIKE ?",
                               (date + "%",)).fetchone()

    def latest(self):
        row = self.db.execute(f"SELECT {','.join(FIELDS)} FROM readings ORDER BY id DESC LIMIT 1").fetchone()
        return dict(zip(FIELDS, row)) if row else None

    def has_decision(self, date: str) -> bool:
        return self.db.execute("SELECT 1 FROM decisions WHERE date = ?", (date,)).fetchone() is not None

    def decision(self, date: str):
        row = self.db.execute("SELECT payload FROM decisions WHERE date = ?", (date,)).fetchone()
        return json.loads(row[0]) if row else None

    def recent_alerts(self, n=20):
        return self.db.execute("SELECT ts, kind, message FROM alerts ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def counts(self):
        return {t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("readings", "decisions", "commands", "alerts", "rejected")}

    def close(self):
        self.db.close()
