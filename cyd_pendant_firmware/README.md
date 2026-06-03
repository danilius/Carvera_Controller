# CYD Pendant Firmware (PlatformIO)

This branch is for the CYD touchscreen pendant work for the Carvera controller. It contains the controller-side bridge plus the firmware for the pendant hardware.

The pendant is split into two small firmware projects:

- `cyd_pendant_firmware`: ESP32/CYD firmware for the touchscreen UI, WiFi, OTA updates, and TCP link to the controller.
- `rp2040_mpg_firmware`: RP2040 firmware for reading the MPG wheel and UI encoder, then sending simple UART messages to the CYD.

The normal controller application remains in the parent repository; the CYD bridge lets it receive jog, probing, ATC, and macro requests from the pendant.

## Current scope

- WiFi STA with local secrets in `include/AppSecrets.h`
- OTA updates via `espota`
- LVGL touchscreen UI for jogging, probing, ATC, and macros
- TCP server on port `9876` for the controller connection
- UART input link from the RP2040 MPG/input board
- Newline-delimited JSON protocol between the controller and CYD

## Setup

1. Copy `include/AppSecrets.example.h` to `include/AppSecrets.h`, then set:
   - `WIFI_SSID`
   - `WIFI_PASS`
2. Update `include/AppConfig.h` for device settings such as button GPIO pins.
3. Adjust `upload_port` in `platformio.ini` to the CYD IP.
4. Build and upload:
   - USB first: `pio run -e cyd_esp32 -t upload`
   - OTA next: `pio run -e cyd_esp32 -t upload --upload-port <CYD_IP>`

## Protocol overview

Controller -> CYD:
- Position updates: `pos`
- Machine/tool state: `machine_state`
- Command results: `jog_result`, `gcode_result`, `tool_result`, `macro_result`
- Available named macros: `macro_list`

CYD -> Controller:
- Jog requests: `jog`, `jog_cont`
- Probing G-code requests: `gcode`
- ATC requests: `tool`
- Macro requests: `macro`
- Status queries: `machine_state_query`, `macro_query`

## Notes

- This targets common ESP32 CYD pinouts. If your board differs, update `build_flags` and GPIOs.
- The controller currently opens the TCP connection to the pendant host/port.
