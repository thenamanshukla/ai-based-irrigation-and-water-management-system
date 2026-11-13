"""Main loop for the Raspberry Pi.

    python -m irrigation.service                      # read Arduino B on the configured serial port
    python -m irrigation.service --port /dev/ttyUSB0
    python -m irrigation.service --stdin              # bench test: paste real packets by hand

Requires:  pip install pyserial   (only for serial mode)
"""
from __future__ import annotations
import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import config
from .hub import Hub
from .store import Store

log = logging.getLogger("service")
RUNNING = True


def _stop(*_):
    global RUNNING
    RUNNING = False


def setup_logging(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(path), logging.StreamHandler(sys.stdout)])


def open_serial(port, baud):
    import serial                                                # pyserial
    return serial.Serial(port, baud, timeout=1)


def run_serial(hub, port, baud):
    ser = None
    while RUNNING:
        try:
            if ser is None:
                ser = open_serial(port, baud)
                hub.send_line = lambda line: ser.write(line.encode())
                log.info("connected to %s at %d baud", port, baud)
            raw = ser.readline()                                 # waits up to 1 s
            if raw:
                hub.handle_line(raw.decode("utf-8", errors="replace"))
            hub.tick()
        except Exception as e:                                   # unplugged, permission, etc.
            log.error("serial problem on %s: %s (retrying in 5 s)", port, e)
            try:
                ser and ser.close()
            except Exception:
                pass
            ser = None
            hub.send_line = _not_connected
            hub.tick()
            time.sleep(5)


def _not_connected(line):
    raise IOError("serial port not connected")


def run_stdin(hub):
    hub.send_line = lambda line: print("VALVE COMMAND ->", line.strip(), flush=True)
    log.info("bench mode: paste one JSON packet per line, Ctrl+D to stop")
    for line in sys.stdin:
        if not RUNNING:
            break
        hub.handle_line(line)
        hub.tick()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Irrigation hub service")
    ap.add_argument("--settings", default="settings.json")
    ap.add_argument("--port")
    ap.add_argument("--stdin", action="store_true", help="read packets typed or pasted on stdin")
    a = ap.parse_args(argv)

    cfg = config.load(a.settings)
    setup_logging(cfg.service.log_path)
    store = Store(cfg.service.db_path)
    try:
        hub = Hub(cfg, store)
    except ValueError as e:
        log.error(str(e))
        return 2
    c = store.counts()
    log.info("database %s: %d readings, %d decisions, %d alerts", cfg.service.db_path,
             c["readings"], c["decisions"], c["alerts"])
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if a.stdin:
        run_stdin(hub)
    else:
        run_serial(hub, a.port or cfg.service.serial_port, cfg.service.baud)
    store.close()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
