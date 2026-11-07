# Arduino firmware

| Folder | Board | Job |
| --- | --- | --- |
| `field_node/` | Arduino UNO A, in the field | Reads sensors every 5 min, logs to SD, shows status on the LCD, sends readings by radio, opens and closes the valve with its own safety rules |
| `gateway/` | Arduino UNO B, at the Pi | Receives readings by radio, prints one JSON line per reading to the Pi, relays valve commands to the field |

Both sketches compile for the Arduino UNO with no warnings:

| Sketch | Flash | RAM (static) |
| --- | --- | --- |
| field_node | 85 % | 73 % (about 550 bytes left for the stack) |
| gateway | 32 % | 21 % |

`packets.h` must stay identical in both folders.

## Libraries (Arduino IDE > Tools > Manage Libraries)

| Library | Author | Used by |
| --- | --- | --- |
| RF24 | TMRh20 | both |
| LiquidCrystal I2C | Frank de Brabander | field node |
| DHT sensor library | Adafruit (accept its "Adafruit Unified Sensor" dependency) | field node |

SD, SPI, Wire and SoftwareSerial come with the IDE. Board: **Arduino Uno**.

## How the two boards talk

NRF24L01 payloads are limited to 32 bytes, so the field node sends a packed 31 byte binary reading.
The gateway converts it to the JSON line the hub expects. Valve commands travel back inside the
radio acknowledgement: the field node polls every 30 seconds, so a command reaches the valve
within about 30 seconds. The gateway drops any command not delivered within 10 minutes, so a
stale command can never open the valve later. The field node ignores repeats of a command id it
has already applied, and reports the id back as `cmd_ack`.

If a sensor fails, its fields are sent as `null`. The hub then rejects that reading and records the
reason, so a broken sensor is visible in `python -m irrigation.cli status` instead of producing a
wrong decision.

## Field node safety rules (work even if the Pi is off)

The valve is closed at power up and closes on its own when any of these is true:

- rain detected (A0 below `RAIN_WET_BELOW`)
- soil moisture at or above `SOIL_FULL_X10` (30.0 %)
- tank level unreadable, or at or below the reserve (`TANK_RESERVE_MM`)
- the commanded time has passed (never more than `MAX_VALVE_MIN`, 90 min)
- no acknowledgement from the gateway for 30 minutes

A hardware watchdog restarts the board if the program hangs for 8 seconds; the valve starts closed after any restart.

## Sensor tests first

Before uploading the full field node, test every part on its own with the programs in
`sensor_tests/` (one per sensor, same pins). See `sensor_tests/README.md` for what each one
shows and which values to copy into `field_node.ino`.

## First run checklist

1. **Find the soil probe registers.** On the Pi, with the USB to RS485 adapter:
   `python tools/find_soil_registers.py`. Copy address, baud and register numbers into the top of
   `field_node.ino`. The defaults (address 1, 4800 baud, registers 0x0000 to 0x0006) suit many
   7 in 1 probes, but not all.
2. **Set the clock.** Open Serial Monitor at 9600 baud, line ending "Newline", and send
   `SET 2026-11-07 10:30:00` with the current local time.
3. **Check I2C addresses.** If the LCD stays blank, its backpack may be 0x3F: change `lcd(0x27, ...)`.
4. **Calibrate the tank sensor.** Mount the IR sensor at least 5 cm above the highest water level
   (it cannot read closer than about 4 cm). Fill the tank in steps and note the `tank_mm` value
   printed in Serial Monitor at each depth. Set `TANK_RESERVE_MM` to the reading at your reserve
   level, and set `tank.sensor_to_floor_m` and `tank.reserve_l` in the hub's `settings.json` to match.
5. **Check the relay direction.** If the valve opens when it should be closed, set `RELAY_ACTIVE_HIGH = false`.
6. **Watch `free_ram`** in Serial Monitor. It should stay above about 150 bytes. If it drops lower,
   tell the software lead before field use.
7. **Radio range.** `RF24_PA_HIGH` and 250 kbps are set for range. If readings show `NOT ACKED`,
   use the PA+LNA module with an adapter board and keep the antennas in line of sight.

## Values that must match the hub

| Firmware | Hub `settings.json` |
| --- | --- |
| `SOIL_FULL_X10` (300 = 30 %) | `soil.theta_fc` (0.30) |
| `TANK_RESERVE_MM` | `tank.sensor_to_floor_m` and `tank.reserve_l` |
| `MAX_VALVE_MIN` (90) | `rules.max_valve_min` (90) |
| Gateway serial 115200 | `service.baud` (115200) |
