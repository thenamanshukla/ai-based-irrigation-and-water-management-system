"""Find the Modbus registers of the 7 in 1 soil probe using the USB to RS485 adapter on the Pi.

Wiring: probe A -> adapter A, probe B -> adapter B, probe power from 5 V or 12 V as its label says.

    python tools/find_soil_registers.py                    # tries /dev/ttyUSB0, common bauds, address 1
    python tools/find_soil_registers.py --port /dev/ttyUSB0 --baud 9600 --addr 1

Prints every register 0x0000 to 0x0030 that answers. Wet the soil around the probe and run it
again: the register that changes most is moisture. Copy the addresses into
firmware/field_node/field_node.ino (REG_MOIST ... REG_K, SOIL_ADDR, SOIL_BAUD).
"""
from __future__ import annotations
import argparse
import struct
import time

import serial


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_register(ser, addr, reg):
    q = struct.pack(">BBHH", addr, 3, reg, 1)
    q += struct.pack("<H", crc16(q))
    ser.reset_input_buffer()
    ser.write(q)
    r = ser.read(7)
    if len(r) != 7 or r[0] != addr or r[1] != 3 or r[2] != 2:
        return None
    if crc16(r[:5]) != struct.unpack("<H", r[5:])[0]:
        return None
    return struct.unpack(">H", r[3:5])[0]


def scan(port, baud, addr, last):
    with serial.Serial(port, baud, timeout=0.3) as ser:
        time.sleep(0.2)
        found = {}
        for reg in range(0, last + 1):
            v = read_register(ser, addr, reg)
            if v is not None:
                found[reg] = v
        return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int)
    ap.add_argument("--addr", type=int, default=1)
    ap.add_argument("--last", type=lambda x: int(x, 0), default=0x30)
    a = ap.parse_args()
    for baud in ([a.baud] if a.baud else [4800, 9600, 2400, 19200]):
        found = scan(a.port, baud, a.addr, a.last)
        if found:
            print(f"Probe answered at {baud} baud, address {a.addr}:")
            for reg, v in found.items():
                print(f"  register 0x{reg:04X}  raw {v:6d}   /10 = {v / 10:7.1f}")
            print("\nTypical meaning: moisture % x10, temperature C x10, EC uS/cm, pH x10, N, P, K mg/kg.")
            return
        print(f"no answer at {baud} baud")
    print("Check wiring (swap A and B), power, and the address printed on the probe label.")


if __name__ == "__main__":
    main()
