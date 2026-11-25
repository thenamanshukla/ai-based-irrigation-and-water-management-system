# AI Based Irrigation and Water Management System

An offline decision support system for small farms that irrigate by gravity from a header tank,
a farm pond or harvested rainwater. Field sensors report soil and water conditions, a Raspberry Pi 5
decides when and how long to water, and an Android app shows the plan in English or Hindi.
A Llama 3.2 1B model runs on the Pi's Arm CPU with ExecuTorch and answers the farmer's questions
using the hub's live data. No internet connection is needed at run time.

Built for the **Bharat AI SoC Student Challenge** (Problem Statement 1: Llama on the Arm CPU with ExecuTorch).

## What it does

| Function | How |
|---|---|
| When to water | Soil moisture from the 7 in 1 probe at 7 cm: watering starts below 35 % and stops at 40 % (tomato prototype) |
| How long to water | One run of 45 minutes, about 1000 ml on the drip rig, stopped early when the soil reaches 40 % |
| Crop water demand | Daily plan from Hargreaves reference evapotranspiration (air temperature) and the FAO 56 tomato crop coefficient |
| Second soil reading | Resistive soil moisture sensor at 4.5 cm, shown beside the probe and used if the probe fails |
| Soil health | pH, EC, soil temperature and N, P, K from the 7 in 1 probe (base for fertigation, next phase) |
| Surroundings | DHT11 air temperature and humidity, MQ135 air quality, IR sensor alert when something comes near the crop |
| Data logging | RTC timestamps and SD card log on the field controller; SQLite database on the Pi |
| Safety | The UNO never opens the valve on wet soil, closes it at 40 %, limits each run to 90 minutes, and follows the 35/40 rule by itself if the Pi is silent for 30 minutes |
| Farmer app | Android app (English and Hindi): live state, plan, both moisture readings, air, IR alerts, trends, manual watering with PIN |
| AI assistant | Llama 3.2 1B on the Pi answers questions such as "Should I water today?" from the live sensor data |

## Hardware (prototype)

| Part | Role | Connection |
|---|---|---|
| Raspberry Pi 5 (4 GB) | Master: hub, database, API, Llama | USB to the UNO; Wi Fi to the phone |
| Arduino UNO | Field controller: reads all sensors, drives the relay | USB serial to the Pi (115200 baud) |
| ESP32 | Wi Fi module; receives every reading from the UNO (UNO D10 to ESP32 RX, ESP32 TX to UNO D11) | Serial, 9600 baud |
| 7 in 1 soil probe (7 cm) | Moisture, temperature, EC, pH, N, P, K | RS485 Modbus through MAX485: RO D9, RE D8, DE D7, DI D6 |
| Resistive soil sensor (4.5 cm) | Second moisture reading | A2 |
| DHT11 | Air temperature and humidity | A0 |
| IR obstacle sensor | Detects objects near the crop | A1 |
| MQ135 | Air quality | A3 |
| DS3231 RTC and SD module | Timestamped data log | I2C A4/A5; SPI |
| Relay and 12 V solenoid valve | Drip line on and off | Relay input on the UNO |
| 12 V battery and DC to DC converter | Power (solar panel charging is the field design) | 5 V to the Pi |

```
Soil probe, soil sensor, DHT11, IR, MQ135, RTC, SD
            |
     Arduino UNO ---- serial ---- ESP32 (Wi Fi)
            | USB
     Raspberry Pi 5 (hub, SQLite, API, Llama 3.2 1B)  ---- Wi Fi ----  Android app
            |
     relay -> 12 V solenoid valve -> drip line (tomato)
```

## Results so far

Llama 3.2 1B Instruct on the Raspberry Pi 5 (4x Cortex-A76, 4 GB), ExecuTorch 1.5, XNNPACK with KleidiAI,
measured with `tools/llama/bench.py` (5 questions, English and Hindi, with the hub's facts in the prompt):

| Measure | Result |
|---|---|
| Answer generation (decode) | 14.1 to 14.5 tokens/s with 4 threads |
| Prompt reading (prefill) | about 130 tokens/s (177 to 195 prompt tokens) |
| Time to first token | 1.4 to 1.5 s |
| Model load (file in page cache) | 2.2 s |
| Total per answer | 4.7 to 12.1 s, depending on answer length |
| Peak memory | 921 MB of 4 GB |
| Temperature | 44 C idle, 72 C peak, no throttling (`throttled=0x0`) |
| Model file | 765 MB |

| Threads | Prefill tokens/s | Decode tokens/s |
|---|---|---|
| 1 | 42.1 | 15.3 |
| 2 | 78.3 | 16.5 |
| 4 | 129.9 | 14.5 |

Prefill is compute bound and scales 3.1 times from 1 to 4 cores; decode is memory bandwidth bound and does not
gain from more threads. The UNO sketch uses 66 % of flash and 74 % of RAM.

**Prototype status.** Sensors, UNO, Pi hub, app and assistant run on real hardware with a potted tomato and a drip line.
Power comes from a 12 V battery; solar charging is part of the field design.

## Where Arm is used

| Part | Chip | Role |
|---|---|---|
| Raspberry Pi 5 hub | Broadcom BCM2712, 4x Arm Cortex-A76 | Hub service, water models, fault detection, database, API, and the Llama assistant through ExecuTorch on the Arm CPU |
| Android phone | Arm Cortex-A based SoC | Runs the farmer app |
| Development Mac | Apple M series (Arm) | Builds the app and exports the Llama model |
| Arduino UNO | ATmega328P (AVR, not Arm) | Field controller. The Arduino UNO R4 (Arm Cortex-M4) is a pin compatible option |
| ESP32 | Xtensa (not Arm) | Wi Fi module |

## Llama on the Arm CPU

| Step | Detail |
|---|---|
| Model | Llama 3.2 1B Instruct (Meta), weights not included in this repository (Llama 3.2 Community License) |
| Quantisation | 8da4w: 4 bit weights in groups of 128, 8 bit dynamic activations; 4 bit embeddings |
| Export | ExecuTorch 1.5 `export_llm` with the XNNPACK partitioner, KV cache and custom SDPA (`tools/llama/export_on_mac.sh`) |
| Runtime | ExecuTorch `llama_main` built for the Pi 5 with `-march=armv8.2-a+dotprod+fp16 -mtune=cortex-a76` and KleidiAI kernels enabled in XNNPACK |
| Grounding | The hub passes its own facts (plan, tank, soil, rain, alerts) and one key sentence; the model only explains and never controls the valve |

Setup and benchmark steps: `tools/llama/README.md`.

## Repository layout

| Path | Contents |
|---|---|
| `irrigation/` | Hub: serial service, real time logic, planner, equations, database, API, Llama assistant |
| `firmware/uno_node/` | Arduino UNO sketch for the prototype (all sensors, relay, SD log, ESP32 link) |
| `firmware/sensor_tests/` | One test sketch per sensor |
| `firmware/field_node/`, `firmware/gateway/` | Earlier two board radio design (NRF24L01), kept for reference |
| `app/` | Android app (Capacitor), English and Hindi |
| `tools/llama/` | Llama export script, export config, benchmark |
| `tools/find_soil_registers.py` | Finds the Modbus registers of the soil probe |
| `deploy/` | systemd units for the hub and the API |

## Quick start

**Raspberry Pi 5** (Raspberry Pi OS Lite 64 bit):

```bash
sudo apt install -y git python3-serial
git clone <this repository> ~/irrigation_brain && cd ~/irrigation_brain
cp settings.example.json settings.json     # set service.planting_date, app_pin, farm_name
sudo cp deploy/irrigation-hub.service deploy/irrigation-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now irrigation-hub irrigation-api
curl localhost:8080/api/health
```

**Arduino:** upload `firmware/uno_node` to the UNO with Arduino IDE (library: DHT sensor library by Adafruit;
SD, Wire, SPI and SoftwareSerial come with the IDE), then plug the UNO into the Pi by USB.

**App:** build steps in `app/README.md`; in the app set the hub address to `<Pi IP>:8080`.

**Llama:** `tools/llama/README.md`.

## Hub details

### Real time behaviour

| When | What |
| --- | --- |
| Every packet (30 s) | Validate, store with Pi time; start watering below 35 %, close at 40 %; IR alert; tank drawdown check when a tank sensor is fitted |
| Every second | Field watchdog (alert if silent for 30 min), manual request check |
| Daily at `plan_time` | Plan only if a reading is less than 30 min old and the last 24 h hold at least 72 readings; otherwise postpone, alert once, retry every 15 min |
| Decision = water | Send the valve command and record it |

The database starts empty and is filled only by real packets; malformed or out of range lines are stored
in the `rejected` table and never used.

### Packet format (UNO to Pi, one JSON object per line every 30 s)

```
{"node":"UNO","ts":"2026-11-25 10:00:00","moisture":36.2,"soil_temp":24.1,"ec":450,"ph":6.5,"n":40,"p":25,"k":120,
 "moisture2":41.0,"air_temp":27.0,"air_rh":71.0,"mq135":312,"ir_object":0,"valve":0,"mode":"pi","sd":1}
```

`moisture` is the 7 in 1 probe, `moisture2` the resistive sensor, `mq135` the raw ADC value, `mode` is `pi` or
`local` (the UNO waters on its own because the Pi is silent). The UNO acknowledges each command with
`{"type":"ack","id":"...","ok":1,"reason":""}`.

Commands from the Pi: `{"cmd":"valve","minutes":45,"id":"a1b2c3d4"}` (0 minutes closes the valve) and
`{"cmd":"time","t":"YYYY-MM-DD HH:MM:SS"}` (sets the UNO's RTC from the Pi clock every hour).

### API (used by the app)

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Name, version, PIN required, assistant installed |
| `GET /api/status` | Latest reading, today's decision, pipe status, alerts |
| `GET /api/history?hours=48` | Readings for charts |
| `GET /api/decisions?days=14` | Daily decisions |
| `POST /api/water` | Manual watering request (PIN; safety rules still apply) |
| `POST /api/pond` | Pond level entered by the farmer (PIN) |
| `POST /api/ask` | Question to the Llama assistant |

### Commands

```bash
python3 -m irrigation.cli status
python3 -m irrigation.cli readings 20
python3 -m irrigation.cli alerts
python3 -m irrigation.service --stdin      # bench mode: paste packets, valve commands are printed
```

## Before field use

- Keep the Pi clock correct (fit the Pi 5 RTC battery when there is no internet).
- Calibrate the resistive sensor (`SOIL2_DRY`, `SOIL2_WET` in the sketch) and set the relay and SD pins.
- Check the soil probe registers with `tools/find_soil_registers.py`.
- The first daily plan needs at least 6 hours of readings.
