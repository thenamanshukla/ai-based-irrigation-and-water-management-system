# Sensor tests: one program per part

Test each part on its own before building the full field node. Every test uses the **same pins as
the real field node**, so the wiring you check here is the wiring you keep.

How to run any test: open the `.ino` file in the Arduino IDE, choose **Arduino Uno**, upload, then
open **Serial Monitor at 9600 baud** (line ending "Newline" where the test asks you to type).

Libraries needed: RF24 (TMRh20), LiquidCrystal I2C (Frank de Brabander), DHT sensor library (Adafruit).

## Order and what to look for

| # | Test | What you will see | It works if | Note down for the real code |
| --- | --- | --- | --- | --- |
| 1 | `t01_relay_valve` | Type `1`/`0` to open and close the valve (auto closes after 10 s) | Relay clicks, water flows only when open | Relay active high or low |
| 2 | `t02_soil_rs485` | All 7 soil values every 3 s with raw numbers | Moisture rises when you water near the probe | Address, baud, register numbers |
| 3 | `t03_dht22` | Air temperature and humidity every 3 s, with daily max and min | Close to a room thermometer; humidity jumps when you breathe on it | Nothing |
| 4 | `t04_rain` | Raw value and a wetness bar every second | Dry about 900 to 1023, drops when wet | Value halfway between dry and wet: `RAIN_WET_BELOW` |
| 5 | `t05_ir_tank` | Distance and water depth every second | Distance matches a ruler within 1 cm | Your tank table (depth vs reading) and the reserve reading: `TANK_RESERVE_MM` |
| 6 | `t06_rtc` | Date and time every second; set with `SET 2026-11-07 10:30:00` | Keeps correct time after unplugging for a minute | Nothing (time is now set) |
| 7 | `t07_lcd_i2c` | List of I2C devices, then text on the LCD | Finds 0x68 (clock) and 0x27 or 0x3F (LCD); text visible | LCD address |
| 8 | `t08_sd_card` | Writes and reads back `TEST.TXT` every 5 s | File grows; opens on a computer | Nothing |
| 9 | `t09_radio_sender` on Arduino A + `t09_radio_receiver` on Arduino B | Counter sent and received every second, success % | Close to 100 % at the real field distance | Whether you need the PA+LNA module or an adapter |
| 10 | `t10_mq135` (optional) | Raw value and change from clean air | Rises near ammonia; first use needs 24 h warm up | Nothing |

When every test passes, upload `field_node` to Arduino A and `gateway` to Arduino B, after copying the
noted values into the settings at the top of `field_node.ino`.

## Common faults

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Soil test says NO REPLY | A and B swapped, wrong baud, probe unpowered | Swap A/B, set `BAUD 9600`, check probe voltage, or run `tools/find_soil_registers.py` on the Pi |
| Soil values look impossible | Different register map | Run the register finder; update the `REG` list |
| DHT READ FAILED | No pull up resistor, loose DATA wire | Add 10 k between DATA and VCC |
| IR reads wrong or jumps | Water closer than 4 cm, sensor tilted, sunlight | Mount at least 5 cm above the highest water, straight down, shaded |
| LCD backlight on, no text | Contrast | Turn the blue screw on the back |
| RTC CLOCK STOPPED | No coin cell or flat cell | Fit a CR2032, then set the time |
| SD card FAILED | Wrong format or card too large | FAT32, 32 GB or smaller |
| Radio NOT FOUND | Wiring, or powered from 5 V and damaged | Check pins; use 3.3 V only |
| Radio mostly LOST | Weak 3.3 V supply, range | 10 uF capacitor or adapter board; PA+LNA module; line of sight |
| Valve opens on `0` | Active low relay board | Set `ACTIVE_HIGH false` here and `RELAY_ACTIVE_HIGH = false` in the field node |
