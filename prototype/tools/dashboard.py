#!/usr/bin/env python3
"""Live terminal dashboard for the Raspberry Pi hub.

Shows the latest field readings, the watering state and the Pi's own health as tiles,
and refreshes every few seconds. Read only: it never sends anything to the UNO.

    cd ~/irrigation_brain/prototype        # or ~/irrigation_brain
    python3 tools/dashboard.py             # Ctrl+C to quit
    python3 tools/dashboard.py --every 2   # refresh every 2 s
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime

START, STOP = 35.0, 40.0

# ---------------------------------------------------------------- colours
R = "\033[0m"
B = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[38;5;71m"
AMBER = "\033[38;5;178m"
RED = "\033[38;5;167m"
BLUE = "\033[38;5;74m"
GREY = "\033[38;5;245m"


def vis_len(s):
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            i = s.index("m", i) + 1
            continue
        out += 1
        i += 1
    return out


def pad(s, w):
    return s + " " * max(0, w - vis_len(s))


def cut(s, w):
    """Trim plain text to w characters."""
    return s if len(s) <= w else s[: max(0, w - 1)] + "…"


def tile(title, value, sub, w, colour=""):
    """Five line box: title, big value, sub line."""
    inner = w - 2
    return [
        GREY + "┌" + "─" * inner + "┐" + R,
        GREY + "│" + R + pad(" " + DIM + cut(title.upper(), inner - 2) + R, inner) + GREY + "│" + R,
        GREY + "│" + R + pad(" " + B + colour + cut(value, inner - 2) + R, inner) + GREY + "│" + R,
        GREY + "│" + R + pad(" " + GREY + cut(sub, inner - 2) + R, inner) + GREY + "│" + R,
        GREY + "└" + "─" * inner + "┘" + R,
    ]


def row(tiles, gap=1):
    return "\n".join((" " * gap).join(t[i] for t in tiles) for i in range(len(tiles[0])))


def bar(pct, width=24):
    if pct is None:
        return GREY + "·" * width + R
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    colour = RED if pct < START else (GREEN if pct >= STOP else AMBER)
    return colour + "█" * filled + R + GREY + "░" * (width - filled) + R


def fmt(v, unit="", nd=1):
    if v is None:
        return "–"
    if isinstance(v, float) and nd == 0:
        return f"{v:.0f}{unit}"
    return f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}"


# ---------------------------------------------------------------- data
def find_db():
    for p in ("data/irrigation.sqlite", "prototype/data/irrigation.sqlite",
              os.path.expanduser("~/irrigation_brain/data/irrigation.sqlite"),
              os.path.expanduser("~/irrigation_brain/prototype/data/irrigation.sqlite")):
        if os.path.exists(p):
            return p
    raise SystemExit("Database not found. Run from the project folder, or pass --db PATH.")


def query(db, sql, args=()):
    try:
        return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def cmd(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def pi_health():
    t = cmd("vcgencmd measure_temp").replace("temp=", "").replace("'C", "")
    thr = cmd("vcgencmd get_throttled").replace("throttled=", "")
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = None
    mem_used = mem_total = None
    try:
        info = dict(l.split(":", 1) for l in open("/proc/meminfo"))
        mem_total = int(info["MemTotal"].split()[0]) // 1024
        mem_used = mem_total - int(info["MemAvailable"].split()[0]) // 1024
    except Exception:
        pass
    up = ""
    try:
        secs = float(open("/proc/uptime").read().split()[0])
        up = f"{int(secs // 3600)}h {int(secs % 3600 // 60)}m"
    except Exception:
        pass
    return {"temp": float(t) if t.replace(".", "", 1).isdigit() else None, "throttled": thr or "–",
            "load": load, "mem_used": mem_used, "mem_total": mem_total, "uptime": up}


def api_health(port):
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=1) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def service(name):
    return cmd(f"systemctl is-active {name}") or "–"


# ---------------------------------------------------------------- screen
def draw(db, port):
    cols = max(84, min(shutil.get_terminal_size((100, 40)).columns, 120))
    w4 = (cols - 3) // 4
    w3 = (cols - 2) // 3
    cols = min(4 * w4 + 3, 3 * w3 + 2)       # every row ends at the same column
    w3 = (cols - 2) // 3
    now = datetime.now()

    last = query(db, "SELECT * FROM readings ORDER BY ts DESC LIMIT 1")
    names = [d[1] for d in query(db, "PRAGMA table_info(readings)")]
    r = dict(zip(names, last[0])) if last else {}
    count = query(db, "SELECT COUNT(*) FROM readings WHERE ts >= datetime('now','localtime','-1 day')")
    today_n = count[0][0] if count else 0
    cmds = query(db, "SELECT ts, minutes, source, id FROM commands ORDER BY ts DESC LIMIT 1")
    alerts = query(db, "SELECT ts, message FROM alerts ORDER BY ts DESC LIMIT 3")
    trend = [x[0] for x in query(db, "SELECT moisture FROM readings WHERE moisture IS NOT NULL ORDER BY ts DESC LIMIT 40")][::-1]

    age = None
    if r.get("ts"):
        try:
            age = (now - datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")).total_seconds()
        except ValueError:
            pass
    online = age is not None and age < 120

    out = []
    head = f"{B} AI BASED IRRIGATION  ·  RASPBERRY PI 5 HUB{R}"
    clock = f"{now:%d %b %Y  %H:%M:%S} "
    out.append(pad(head, cols - len(clock)) + GREY + clock + R)
    state = (GREEN + "● FIELD ONLINE" if online else RED + "● FIELD NOT REPORTING") + R
    ago = f"last reading {int(age)} s ago" if age is not None else "no readings yet"
    out.append(f" {state}   {GREY}{ago}  ·  {today_n} readings in 24 h{R}")
    out.append("")

    # soil moisture banner
    m = r.get("moisture")
    m2 = r.get("moisture2")
    use = m if m is not None else m2
    if r.get("valve"):
        decision, dc = "WATERING NOW", BLUE
    elif use is None:
        decision, dc = "WAITING FOR SOIL READING", GREY
    elif use < START:
        decision, dc = "DRY: WATERING STARTS", RED
    elif use >= STOP:
        decision, dc = "SOIL OK: NO WATERING NEEDED", GREEN
    else:
        decision, dc = "SOIL OK: WATCHING", AMBER
    inner = cols - 2
    out.append(GREY + "┌" + "─" * inner + "┐" + R)
    line = f" {DIM}SOIL MOISTURE (7 IN 1 PROBE, 7 cm){R}   {B}{fmt(m, ' %')}{R}   {bar(m, 30)}   {GREY}start {START:.0f} %  stop {STOP:.0f} %{R}"
    out.append(GREY + "│" + R + pad(line, inner) + GREY + "│" + R)
    spark = ""
    if trend:
        ticks = "▁▂▃▄▅▆▇█"
        lo, hi = min(trend), max(trend)
        spark = "".join(ticks[int((v - lo) / (hi - lo + 1e-9) * 7)] for v in trend)
    line = f" {B}{dc}{decision}{R}   {GREY}last 40 readings {R}{BLUE}{spark}{R}"
    out.append(GREY + "│" + R + pad(line, inner) + GREY + "│" + R)
    out.append(GREY + "└" + "─" * inner + "┘" + R)

    # soil tiles
    out.append(row([
        tile("Soil sensor 4.5 cm", fmt(m2, " %"), "resistive", w4),
        tile("Soil temperature", fmt(r.get("soil_temp"), " °C"), "7 in 1 probe", w4),
        tile("EC", fmt(r.get("ec"), " µS/cm", 0), "salinity", w4),
        tile("pH", fmt(r.get("ph")), "7 in 1 probe", w4),
    ]))
    npk = "  ".join(f"{k.upper()} {fmt(r.get(k), '', 0)}" for k in ("n", "p", "k"))
    ir = r.get("ir_object")
    mq = r.get("mq135")
    mq_txt = "–" if mq is None else ("good" if mq < 300 else "moderate" if mq < 500 else "poor")
    out.append(row([
        tile("N  P  K (mg/kg)", npk, "nutrients", w4),
        tile("Air", f"{fmt(r.get('air_temp'), ' °C')}  {fmt(r.get('air_rh'), ' %', 0)}", "DHT11 temp, humidity", w4),
        tile("Air quality", fmt(mq, "", 0), f"MQ135 raw, {mq_txt}", w4, GREEN if mq_txt == "good" else AMBER if mq_txt == "moderate" else RED if mq_txt == "poor" else ""),
        tile("IR sensor", "OBJECT NEAR" if ir else "clear", "near the crop", w4, RED if ir else GREEN),
    ]))

    # valve and control
    valve = r.get("valve")
    if cmds:
        cts, cmin, csrc, cid = cmds[0]
        ctxt = f"{cmin:.0f} min, {csrc}" if cmin else f"stop, {csrc}"
        csub = f"{cts[11:]}  id {cid}"
    else:
        ctxt, csub = "none yet", ""
    out.append(row([
        tile("Valve", "OPEN" if valve else "closed", "solenoid via relay", w3, BLUE if valve else GREY),
        tile("Last command", ctxt, csub, w3),
        tile("Control", (r.get("mode") or "–").upper(), "PI or LOCAL (UNO)", w3),
    ]))

    # Pi health
    h = pi_health()
    api = api_health(port)
    temp = h["temp"]
    tcol = GREEN if temp is not None and temp < 70 else AMBER if temp is not None and temp < 80 else RED
    mem = f"{h['mem_used']} / {h['mem_total']} MB" if h["mem_used"] else "–"
    llm = "ready" if api and api.get("assistant") else "not installed" if api else "API down"
    out.append(row([
        tile("CPU temperature", fmt(temp, " °C"), f"throttled {h['throttled']}", w4, tcol),
        tile("Memory", mem, f"load {fmt(h['load'], '', 2)}", w4),
        tile("Services", f"hub {service('irrigation-hub')}", f"api {service('irrigation-api')}", w4,
             GREEN if service("irrigation-hub") == "active" else RED),
        tile("Llama 3.2 1B", llm, f"Arm A76, up {h['uptime']}", w4, GREEN if llm == "ready" else AMBER),
    ]))

    # alerts
    out.append(f" {DIM}RECENT ALERTS{R}")
    if alerts:
        for ts, msg in alerts:
            out.append(f"  {GREY}{ts[5:16]}{R}  {msg[: cols - 20]}")
    else:
        out.append(f"  {GREY}none{R}")
    out.append("")
    out.append(f" {GREY}Ctrl+C to quit{R}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Live dashboard for the irrigation hub")
    ap.add_argument("--db", help="path to irrigation.sqlite")
    ap.add_argument("--every", type=float, default=3.0, help="refresh interval in seconds")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--once", action="store_true", help="draw one frame and exit")
    a = ap.parse_args()
    path = a.db or find_db()
    print("\033[?25l", end="")                      # hide cursor
    try:
        while True:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
            frame = draw(db, a.port)
            db.close()
            print("\033[H\033[2J" + frame, flush=True)
            if a.once:
                break
            time.sleep(a.every)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")                  # show cursor


if __name__ == "__main__":
    main()
