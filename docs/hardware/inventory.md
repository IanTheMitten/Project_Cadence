# Hardware inventory

Update in place. Date-stamp each change in `build-log.md`.

Last updated: 2026-10-17 (seeded from `CLAUDE.md` and specs; verify against the bench and correct).

## Boards

| Board | Role | Status | Flashed with | Notes |
|---|---|---|---|---|
| ESP32-S3 #1 | Speaker + mic (voice) | working (per repo; confirm) | `voice_chat/` (harness `/session` client) | Switch to root project or `mic_test/` by reflashing; only one image at a time. |
| ESP32-S3 #2 | Bedroom ceiling lamp (`bedroom-ceiling`) | 24 V bench test passed 2026-11-10, ready to mount | `lamp/` (Cadence `/peer` device) | MAC `20:6e:f1:d6:e8:bc`, 8 MB flash, CH34x USB-serial. Wiring below. |
| ESP32-S3 #3, #4 | Lamps / CSI nodes | planned | none | Spare boards for the CSI ground tests. Fill in per-board notes as they are used. |

## Speaker + mic board wiring

| Signal | Speaker DAC/amp (I2S TX, `I2S_NUM_0`) | INMP441 mic (I2S RX, `I2S_NUM_1`) |
|---|---|---|
| BCLK / SCK | GPIO15 | GPIO5 |
| WS / LRCLK | GPIO16 | GPIO6 |
| Data | GPIO17 (dout) | GPIO4 (din) |
| Format | 16-bit stereo 44.1 kHz | 32-bit mono (left slot) 16 kHz |

INMP441: `L/R` to GND (left slot), `VDD` 3.3 V (not 5 V).

Not yet recorded here (fill in): DAC/amp part number, speaker driver, power supply, enclosure.

## Ceiling lamp wiring (board #2)

24 V CCT strip, low-side switched by two IRLZ44N.

| Item | Connection |
|---|---|
| 24 V PSU (+) | strip +24 V, buck VIN+ |
| 24 V PSU (-) | buck VIN-, both MOSFET sources |
| Buck VOUT (5 V) | ESP32 5V/VIN and GND (buck must share VIN-/VOUT- ground) |
| GPIO2 | 220 ohm to Gate 1, 10 k gate-to-GND; Drain 1 = strip WW (-) |
| GPIO4 | 220 ohm to Gate 2, 10 k gate-to-GND; Drain 2 = strip CW (-) |

Gate drive is 3.3 V through 220 ohm, so PWM is 2 kHz (switching about 5-10 us per edge). If either channel draws over about 3 A, add a TC4427 gate driver on 5 V. Do not power from USB and the buck at once.

## Planned parts (not yet bought or built)

LD2410 presence radar (x3), LD6002 vitals radar, Pi 4 with NoIR camera and IR light, lamp drivers (tunable white + RGB strip). See `docs/specs/2026-10-13-csi-ground-tests.md`.
