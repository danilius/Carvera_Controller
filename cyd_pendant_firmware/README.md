# CYD Pendant Firmware (PlatformIO)

This is a standalone CYD firmware scaffold that pairs with the controller CYD pendant class.

## Current scope

- WiFi STA with hardcoded credentials
- OTA updates via `espota`
- LVGL status screen (no touch)
- TCP server on port `9876` for controller connection
- Newline-delimited JSON protocol
- Button-driven actions:
  - `tool_action_confirm` for firmware-triggered manual tool change
  - `tool_action_request` for manual clamp/unclamp when machine is not running

## Setup

1. Update `include/AppConfig.h`:
   - `WIFI_SSID`
   - `WIFI_PASS`
   - button GPIO pins
2. Adjust `upload_port` in `platformio.ini` to the CYD IP.
3. Build and upload:
   - USB first: `pio run -e cyd_esp32 -t upload`
   - OTA next: `pio run -e cyd_esp32 -t upload --upload-port <CYD_IP>`

## JSON messages

Controller -> CYD:
- `{"type":"pos","x":...,"y":...,"z":...}`
- `{"type":"mdi","level":"normal|error","message":"..."}`
- `{"type":"tool_action_required","action":"clamp|unclamp","tool":N,"message":"..."}`
- `{"type":"tool_action_result","action":"clamp|unclamp","ok":true|false,"reason":"..."}`

CYD -> Controller:
- `{"type":"tool_action_confirm","action":"clamp|unclamp"}`
- `{"type":"tool_action_request","action":"clamp|unclamp"}`

## Notes

- This targets common ESP32 CYD pinouts. If your board differs, update `build_flags` and GPIOs.
- The controller currently opens the TCP connection to the pendant host/port.
