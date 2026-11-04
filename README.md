# Irrigation hub (real-time)

The decision engine for AI based irrigation and water management. It runs on the Raspberry Pi 5,
reads real packets from Arduino B over USB serial, and makes decisions on the Pi's own clock.

**No sample data is shipped.** The database is created empty on first start and is filled only by
packets received from the field node. The simulator exists only inside `tests/` and is never
imported by the service.

## First start on the Pi

```bash
pip install -r requirements.txt          # pyserial
cp settings.example.json settings.json
nano settings.json                        # set service.planting_date, tank and dripper values
python -m irrigation.service              # reads /dev/ttyACM0 by default
```

The service refuses to start until `planting_date` is set.

Run it on boot:

```bash
sudo cp deploy/irrigation-hub.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now irrigation-hub
journalctl -u irrigation-hub -f
```

## Bench test before the field node is ready

Type or paste real packets by hand; valve commands are printed instead of sent:

```bash
python -m irrigation.service --stdin
{"moisture": 28.5, "air_temp": 29.0, "tank_cm": 8.0, "rain": 0, "valve": 0}
```

## Packet format (Arduino B to Pi, one JSON object per line)

| Field | Unit | Required |
| --- | --- | --- |
| `moisture` | % volumetric, 0 to 100 | yes |
| `air_temp` | deg C | yes |
| `tank_cm` | IR distance, sensor to water surface, cm | yes |
| `rain`, `valve` | 0 or 1 | yes |
| `air_rh`, `soil_temp`, `ec`, `ph`, `n`, `p`, `k`, `node`, `ts` | as reported | no |

Out of range or malformed lines are stored in the `rejected` table and logged, never used.
The Pi's receive time is the authoritative timestamp; the node's `ts` is kept for reference.

Valve command (Pi to Arduino B): `{"cmd":"valve","minutes":22.0,"id":"a1b2c3d4"}`

## Commands (safe while the service runs)

```bash
python -m irrigation.cli status          # counts, latest reading, pond, pipe status
python -m irrigation.cli readings 20
python -m irrigation.cli alerts
python -m irrigation.cli set-pond 120    # litres in the pond (until a pond sensor exists)
python -m irrigation.cli water 15        # manual request; rain, reserve and wet soil still block it
```

## What happens in real time

| When | What |
| --- | --- |
| Every packet | Validate, store with Pi time, update `data/status.json`, check tank drawdown if the valve is open |
| Every second | Field watchdog (alert if silent for 30 min), manual request check |
| Daily at `plan_time` | Plan only if a reading is less than 30 min old and the last 24 h hold at least 72 readings; otherwise postpone, alert once, retry every 15 min |
| Decision = water | Send the valve command and record it in `commands` |

Leak and clog detection learns the normal flow during the first watering runs; that calibration is
saved in the database and survives restarts.

## Database (`data/irrigation.sqlite`)

`readings`, `decisions`, `commands`, `alerts`, `rejected`, `state`. Every write is committed immediately,
so a power cut loses at most the packet in flight.

## Files

| File | Role |
| --- | --- |
| `irrigation/service.py` | Main loop: serial reader with auto reconnect, bench mode |
| `irrigation/hub.py` | Real-time logic: storage, scheduling, fault watch, valve commands, status |
| `irrigation/packet.py` | Packet contract and validation |
| `irrigation/planner.py` | Daily decision from Eqs. (1) to (8) |
| `irrigation/models.py` | The equations |
| `irrigation/store.py` | SQLite access |
| `irrigation/cli.py` | Farmer and developer commands |
| `irrigation/config.py` | Settings and defaults |
| `tests/` | 27 tests, including a 45 day season through the real hub and a real service process |

```bash
python -m unittest discover -s . -p "test_*.py"
```

## Before trusting it in the field

- Set the Pi clock correctly. With no internet, fit the Pi 5 RTC battery or set the time on boot.
- Calibrate `tank` and `emitters` values from your own rig (Appendix A.2 and A.6 of the system document).
- Enter the pond level with `set-pond` until a pond sensor is installed; it is assumed 0 otherwise.
- The first daily plan needs at least 6 hours of readings, so expect the first decision the morning after you start.
