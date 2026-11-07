// Radio messages between the field node (Arduino A) and the gateway (Arduino B).
// Keep this file IDENTICAL in field_node/ and gateway/.
// NRF24L01 payloads are limited to 32 bytes, so readings travel as a packed binary
// struct; the gateway converts them to the JSON line the Raspberry Pi expects.
#pragma once
#include <stdint.h>

#define RADIO_CHANNEL   90                 // 2.490 GHz, away from most Wi Fi channels
#define FIELD_ADDRESS   "IRRG1"            // field node writes, gateway listens on pipe 1

#define MSG_READING 1
#define MSG_COMMAND 2
#define MSG_POLL    3

// flags bits in Reading
#define F_RAIN    0x01
#define F_VALVE   0x02
#define F_SOIL_OK 0x04
#define F_DHT_OK  0x08
#define F_IR_OK   0x10
#define F_RTC_OK  0x20
#define F_SD_OK   0x40

struct __attribute__((packed)) Reading {
  uint8_t  type;           // MSG_READING
  uint8_t  node;           // 'A'
  uint16_t seq;            // increments every reading
  uint32_t ts;             // RTC local time, seconds since 2000-01-01
  int16_t  moisture_x10;   // % volumetric x10
  int16_t  soil_temp_x10;  // deg C x10
  uint16_t ec;             // uS/cm
  uint8_t  ph_x10;         // pH x10
  uint16_t n, p, k;        // mg/kg
  uint16_t tank_mm;        // IR distance, sensor to water surface, mm
  int16_t  air_temp_x10;   // deg C x10
  uint8_t  air_rh;         // %
  uint8_t  flags;          // F_* bits
  uint32_t last_cmd;       // id of the last valve command received (0 = none)
};

struct __attribute__((packed)) Command {
  uint8_t  type;           // MSG_COMMAND
  uint8_t  node;           // 'A'
  uint16_t minutes_x10;    // valve open time x10
  uint32_t id;             // from the hub, 8 hex characters
};

struct __attribute__((packed)) Poll {
  uint8_t  type;           // MSG_POLL
  uint8_t  node;
};

static_assert(sizeof(Reading) <= 32, "Reading must fit one NRF24L01 payload");
static_assert(sizeof(Command) <= 32, "Command must fit one NRF24L01 payload");
