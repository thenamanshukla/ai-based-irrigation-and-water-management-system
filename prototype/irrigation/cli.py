"""Farmer and developer commands. Safe to run while the service is running.

    python -m irrigation.cli status
    python -m irrigation.cli alerts
    python -m irrigation.cli readings 10
    python -m irrigation.cli set-pond 120        # litres currently in the pond
    python -m irrigation.cli water 20            # request 20 minutes now (safety rules still apply)
"""
from __future__ import annotations
import argparse
import json
import sys

from . import config
from .store import Store


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default="settings.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("alerts")
    r = sub.add_parser("readings"); r.add_argument("n", type=int, nargs="?", default=10)
    p = sub.add_parser("set-pond"); p.add_argument("litres", type=float)
    w = sub.add_parser("water"); w.add_argument("minutes", type=float)
    a = ap.parse_args(argv)

    cfg = config.load(a.settings)
    store = Store(cfg.service.db_path)

    if a.cmd == "status":
        print(json.dumps(store.counts(), indent=2))
        latest = store.latest()
        print("latest reading:", json.dumps(latest) if latest else "none yet")
        print("pond litres:", store.get_state("pond_l", "not set"))
        print("pipe status:", store.get_state("pipe_status", "not yet checked"))
    elif a.cmd == "alerts":
        rows = store.recent_alerts(50)
        print("\n".join(f"{t}  {k:<14} {m}" for t, k, m in reversed(rows)) or "no alerts")
    elif a.cmd == "readings":
        rows = store.db.execute("SELECT ts, moisture, moisture2, air_temp, air_rh, mq135, ir_object, valve "
                                "FROM readings ORDER BY id DESC LIMIT ?", (a.n,)).fetchall()
        print("ts                   7in1%  soil2%  air_C   rh%  mq135  ir  valve")
        for row in reversed(rows):
            print("{}  {!s:>5}  {!s:>6}  {!s:>5}  {!s:>4}  {!s:>5}  {!s:>2}  {!s:>5}".format(*row))
        if not rows:
            print("no readings yet")
    elif a.cmd == "set-pond":
        if not 0 <= a.litres <= 1e7:
            sys.exit("litres out of range")
        store.set_state("pond_l", a.litres)
        print(f"pond set to {a.litres:g} L")
    elif a.cmd == "water":
        store.set_state("manual_request", {"minutes": a.minutes})
        print(f"requested {a.minutes:g} min; the service applies safety rules and will log the result in alerts")
    store.close()


if __name__ == "__main__":
    main()
