# System block diagram, IEEE style. Run: python3 make.py out.svg
import sys, base64
W, H = 2600, 1815
o = []
def a(s): o.append(s)
esc0 = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
import re as _re
def esc(t):
    """Escape text and set every Arm term in bold black."""
    parts = _re.split(r"(\b(?:Arm|ARM|arm64-v8a|arm64|aarch64|Armv8\.2-A)\b)", t)
    return "".join(f'<tspan font-weight="bold" fill="#000">{esc0(x)}</tspan>' if i % 2 else esc0(x) for i, x in enumerate(parts))

def frame(x, y, w, h, title, dashed=False, size=17):
    da = ' stroke-dasharray="12 7"' if dashed else ""
    sw = 2.5 if dashed else 3
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#000" stroke-width="{sw}"{da}/>')
    a(f'<text x="{x+10}" y="{y+22}" font-size="{size}" font-weight="bold" font-style="italic">{esc(title)}</text>')

def box(x, y, w, h, name, spec):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="url(#g)" stroke="#5874B8" stroke-width="2"/>')
    cx = x + w / 2
    a(f'<text x="{cx}" y="{y+h/2-4}" text-anchor="middle" font-size="16" font-weight="bold">{esc(name)}</text>')
    a(f'<text x="{cx}" y="{y+h/2+16}" text-anchor="middle" font-size="13">{esc(spec)}</text>')

STY = {
    "power": 'stroke="#D0021B" stroke-width="4.5"',
    "comm": 'stroke="#1E8E3E" stroke-width="4.5"',
    "ctrl": 'stroke="#E08A00" stroke-width="4.5"',
    "bus": 'stroke="#7B3FA8" stroke-width="3.5" stroke-dasharray="10 6"',
    "wifi": 'stroke="#000" stroke-width="3.5" stroke-dasharray="2 7" stroke-linecap="round"',
    "phys": 'stroke="#8A8A8A" stroke-width="3.5" stroke-dasharray="12 8"',
    "data": 'stroke="#444" stroke-width="3" marker-end="url(#arr)"',
    "act": 'stroke="#7A4A1E" stroke-width="4.5"',
}
def wire(pts, kind):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    if kind == "analog":
        a(f'<path d="{d}" fill="none" stroke="#2A6FDB" stroke-width="7"/>')
        a(f'<path d="{d}" fill="none" stroke="#fff" stroke-width="2.4"/>')
    else:
        a(f'<path d="{d}" fill="none" {STY[kind]} stroke-linejoin="miter"/>')

def label(x, y, t, anchor="middle"):
    a(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="13" fill="#000">{esc(t)}</text>')

def dot(x, y, c):
    a(f'<circle cx="{x}" cy="{y}" r="5" fill="{c}"/>')

a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Arial, Helvetica, sans-serif">')
a('<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#EEF2FA"/><stop offset="1" stop-color="#C3D1EB"/></linearGradient>'
  '<marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 z" fill="#444"/></marker></defs>')
a(f'<rect width="{W}" height="{H}" fill="#fff"/>')
a('<text x="40" y="52" font-size="30" font-weight="bold">AI Based Irrigation and Water Management System: System Block Diagram</text>')
a('<text x="40" y="84" font-size="17" fill="#000">Arduino UNO field controller and Raspberry Pi 5 hub running Llama 3.2 1B on the Arm CPU with ExecuTorch, drip irrigation of a potted tomato</text>')

R = [229, 339, 449, 559, 669, 779]          # row centres
BH = 78
top = lambda c: c - BH / 2

# ---------------- frames
frame(40, 130, 460, 720, "Sensor board")
frame(40, 880, 460, 160, "Prototype photos")
frame(540, 130, 560, 910, "Field controller")
frame(575, 160, 250, 850, "Arduino UNO")
frame(595, 850, 210, 140, "Firmware: uno_node", dashed=True, size=14)
frame(1160, 130, 640, 670, "Main controller: Raspberry Pi 5 (Arm)")
frame(1190, 160, 580, 130, "Broadcom BCM2712 Arm SoC", size=15)
frame(1190, 310, 580, 230, "Software on Arm (Raspberry Pi OS Lite, aarch64)", dashed=True, size=15)
frame(1870, 130, 690, 1120, "User (Arm based phone)")
frame(540, 1100, 1260, 150, "Power")

# ---------------- sensor board
SX, SW = 110, 330
box(SX, top(R[0]), SW, BH, "7 in 1 soil probe", "Moisture, T, EC, pH, N, P, K at 7 cm")
box(SX, top(R[1]), SW, BH, "MAX485", "RO D9, DI D6, DE D7, RE D8")
box(SX, top(R[2]), SW, BH, "Soil moisture sensor", "Resistive, 4.5 cm depth, A2")
box(SX, top(R[3]), SW, BH, "DHT11", "Air temperature and humidity, A0")
box(SX, top(R[4]), SW, BH, "MQ135", "Air quality, analog, A3")
box(SX, top(R[5]), SW, BH, "IR obstacle sensor", "Object near the crop, A1")

# ---------------- field controller
box(600, 190, 200, 628, "ATmega328P", "16 MHz, 32 KB flash")
box(610, 880, 190, BH, "Sensor loop", "JSON every 30 s")
CX, CW = 880, 190
box(CX, top(R[0]), CW, BH, "DS3231 RTC", "Time stamp, 0x68")
box(CX, top(R[1]), CW, BH, "SD card module", "Local data log")
box(CX, top(R[2]), CW, BH, "ESP32", "Wi-Fi module")
box(CX, top(R[4]), CW, BH, "Relay module", "1 channel, 5 V coil")
box(CX, top(R[5]), CW, BH, "Solenoid valve", "12 V, normally closed")

# ---------------- Raspberry Pi 5
box(1220, 190, 520, BH, "4x Arm Cortex-A76", "2.4 GHz, Armv8.2-A, Arm NEON, dot product")
BW = 170
box(1210, 345, BW, BH, "Hub service", "Python on Arm, 35/40 %")
box(1400, 345, BW, BH, "SQLite", "Readings, plans, alerts")
box(1590, 345, BW, BH, "HTTP API", "JSON, port 8080")
box(1590, 450, BW, BH, "Llama 3.2 1B", "ExecuTorch, Arm KleidiAI")
box(1210, 569, BW, BH, "USB host", "Serial, 115200 baud")
box(1590, 569, BW, BH, "Wi-Fi radio", "802.11ac")
box(1210, 680, BW, BH, "LPDDR4X RAM", "4 GB")
box(1400, 680, BW, BH, "USB flash drive", "16 GB, OS and model")
box(1590, 680, BW, BH, "Power input", "USB-C, 5 V")

# ---------------- user
box(1890, 450, 265, BH, "Farmer", "English or Hindi")
box(1890, 569, 265, BH, "Android app", "Capacitor, runs on Arm (arm64)")
box(1890, 680, 265, BH, "App screens", "Today, Trends, Water, Ask, Settings")
box(1890, 820, 265, BH, "Android emulator test", "arm64-v8a image, Apple M (Arm)")
box(1890, 940, 265, BH, "APK build", "Android Studio on Arm Mac")

# ---------------- power
box(570, 1141, 200, BH, "Solar panel", "Planned charging")
box(800, 1141, 200, BH, "12 V battery", "Field supply")
box(1575, 1141, 200, BH, "DC-DC converter", "12 V to 5 V, 5 A")

# ================= wires
# soil probe chain
wire([(275, 268), (275, 300)], "comm"); label(285, 289, "RS485", "start")
wire([(440, 331), (600, 331)], "comm"); label(470, 324, "UART")
wire([(440, 347), (600, 347)], "ctrl"); label(470, 366, "DE/RE")
wire([(440, 449), (600, 449)], "analog"); label(470, 438, "Analog")
wire([(440, 559), (600, 559)], "comm"); label(470, 549, "1-Wire")
wire([(440, 669), (600, 669)], "analog"); label(470, 658, "Analog")
wire([(440, 779), (600, 779)], "ctrl"); label(470, 769, "Digital")
# MCU peripherals
wire([(800, 229), (880, 229)], "comm"); label(852, 220, "I2C")
wire([(800, 339), (880, 339)], "comm"); label(852, 330, "SPI")
wire([(800, 449), (880, 449)], "comm"); label(852, 440, "UART")
wire([(800, 669), (880, 669)], "ctrl"); label(852, 660, "D5")
wire([(975, 708), (975, 740)], "act")
wire([(1070, 449), (1135, 449)], "wifi"); label(1130, 438, "Wi-Fi")
wire([(700, 818), (700, 850)], "bus")
# UNO to Pi
wire([(800, 600), (1210, 600)], "comm"); label(1005, 592, "USB serial, 115200 baud")
wire([(800, 616), (1210, 616)], "power"); label(1130, 637, "USB 5 V")
# physical
# actuator power
wire([(900, 1141), (900, 1090), (1120, 1090), (1120, 669), (1070, 669)], "act"); label(1128, 1080, "12 V valve supply", "start")
# power
wire([(770, 1180), (800, 1180)], "power")
wire([(1000, 1180), (1575, 1180)], "power"); label(1290, 1172, "12 V")
wire([(1675, 1141), (1675, 758)], "power"); label(1685, 1000, "5 V, 5 A", "start")
# Pi internal buses
wire([(1480, 268), (1480, 310)], "bus")
wire([(1295, 758), (1295, 780), (1175, 780), (1175, 229), (1220, 229)], "bus")
wire([(1485, 758), (1485, 780), (1295, 780)], "bus"); dot(1295, 780, "#7B3FA8")
# Pi data flow
wire([(1295, 569), (1295, 426)], "data")
wire([(1380, 384), (1397, 384)], "data")
wire([(1570, 384), (1587, 384)], "data")
wire([(1667, 423), (1667, 447)], "data")
wire([(1683, 450), (1683, 426)], "data")
wire([(1760, 384), (1782, 384), (1782, 552), (1675, 552), (1675, 566)], "data")
# Pi to phone
wire([(1760, 608), (1890, 608)], "wifi"); label(1835, 597, "Wi-Fi"); label(1835, 632, "HTTP")
wire([(2022, 528), (2022, 569)], "phys"); label(2032, 553, "Touch", "start")
wire([(2022, 647), (2022, 680)], "bus")
wire([(2022, 758), (2022, 820)], "bus")
wire([(2022, 898), (2022, 940)], "bus")

# ================= photos
def photo(name, x, y, w, h, cap=None):
    d = base64.b64encode(open("img/" + name, "rb").read()).decode()
    a(f'<image href="data:image/jpeg;base64,{d}" x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"/>')
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#000" stroke-width="1"/>')
    if cap:
        a(f'<text x="{x + w/2}" y="{y + h + 16}" text-anchor="middle" font-size="12.5" fill="#000">{esc(cap)}</text>')
photo("setup.jpg", 58, 908, 200, 106, "UNO, ESP32 and sensor wiring")
photo("sensors.jpg", 282, 908, 200, 106, "MQ135 and DHT11 on the breadboard")
photo("app_full.jpg", 2185, 160, 360, 878)
a('<text x="2365" y="1062" text-anchor="middle" font-size="13" fill="#000">App dashboard, Today screen (bench test data)</text>')
wire([(2155, 719), (2185, 719)], "bus")

# ================= water path
frame(40, 1280, 2520, 345, "Water path: gravity drip irrigation")
names = [("tank.jpg", "Water tank", "Gravity head to the drip line"),
         ("filter.jpg", "Screen filter", "Keeps emitters from clogging"),
         ("valve.jpg", "Solenoid valve", "12 V, opened by the relay"),
         ("drip.jpg", "Drip line", "45 min run, about 1000 ml"),
         ("probe_pot.jpg", "Tomato pot", "Root zone of the plant")]
PW = 300
for i, (img, n, sp) in enumerate(names):
    cx = 40 + 2520 * (i + 0.5) / 5
    photo(img, cx - PW/2, 1318, PW, 180)
    box(cx - PW/2, 1512, PW, BH, n, sp)
    if i < 4:
        nx = 40 + 2520 * (i + 1.5) / 5
        wire([(cx + PW/2, 1551), (nx - PW/2 - 4, 1551)], "phys")
        a(f'<path d="M{nx - PW/2 - 12},{1545} L{nx - PW/2},{1551} L{nx - PW/2 - 12},{1557} z" fill="#8A8A8A"/>')
label(2550, 1615, "Tank, filter, valve and drip line photos: Wikimedia Commons. Pot, sensor and app photos: project prototype.", "end")

# ================= legend
LX, LY = 40, 1062
a(f'<rect x="{LX}" y="{LY}" width="460" height="188" fill="#fff" stroke="#000" stroke-width="1.5"/>')
a(f'<text x="{LX+14}" y="{LY+24}" font-size="16" font-weight="bold">Legend</text>')
items = [("power", "Power supply"), ("comm", "Serial bus (SPI, I2C, UART)"), ("ctrl", "Control signal"),
         ("bus", "Internal bus"), ("analog", "Analog signal"), ("wifi", "Wi-Fi link"),
         ("phys", "Water or touch"), ("data", "Data flow"), ("act", "Actuator power")]
for i, (k, t) in enumerate(items):
    col, row = divmod(i, 5)
    x0, y = LX + 14 + col * 228, LY + 50 + row * 30
    wire([(x0, y), (x0 + 50, y)], k)
    a(f'<text x="{x0 + 60}" y="{y+5}" font-size="12.5">{esc(t)}</text>')

# ================= abbreviations
AY = 1655
a(f'<rect x="40" y="{AY}" width="2520" height="140" fill="#fff" stroke="#000" stroke-width="1.5"/>')
a(f'<text x="54" y="{AY+26}" font-size="16" font-weight="bold">Abbreviations</text>')
ab = ["API: Application Programming Interface", "DC: Direct Current", "EC: Electrical Conductivity",
      "ET0: Reference Evapotranspiration", "HTTP: Hypertext Transfer Protocol", "I2C: Inter Integrated Circuit",
      "IR: Infrared", "JSON: JavaScript Object Notation", "LPDDR4X: Low Power Double Data Rate 4X",
      "N, P, K: Nitrogen, Phosphorus, Potassium", "NEON: Arm SIMD instruction extension", "RAM: Random Access Memory",
      "RS485: Serial line standard (Modbus RTU)", "RTC: Real Time Clock", "RTU: Remote Terminal Unit",
      "SD: Secure Digital", "SoC: System on Chip", "SPI: Serial Peripheral Interface",
      "T: Temperature", "UART: Universal Asynchronous Receiver Transmitter", "USB: Universal Serial Bus",
      "USB-C: USB Type C connector", "Wi-Fi: Wireless LAN (IEEE 802.11)", "KleidiAI: Arm optimised AI kernels", "aarch64, arm64: 64 bit Arm architecture", "arm64-v8a: Android 64 bit Arm ABI", "ABI: Application Binary Interface", "APK: Android app package", "Armv8.2-A: Arm architecture version"]
cols = 6
per = (len(ab) + cols - 1) // cols
for i, t in enumerate(ab):
    c, r = divmod(i, per)
    a(f'<text x="{54 + c*418}" y="{AY+52 + r*18}" font-size="12.5">{esc(t)}</text>')
a('</svg>')
open(sys.argv[1], "w").write("\n".join(o))
print("ok")
