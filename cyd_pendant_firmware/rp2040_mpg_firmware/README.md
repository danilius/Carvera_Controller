# RP2040 MPG Firmware

PlatformIO firmware for the RP2040 input co-processor used by the CYD pendant.

This starts from the tested MPG wheel proof-of-concept at:

`C:\Users\plane\OneDrive\Documents\PlatformIO\Projects\RP2040 MPG test 1`

Current behavior:

- Reads the MPG quadrature encoder on GPIO2/GPIO3 using RP2040 PIO.
- Uses GP4/GP5 for the UART link to the CYD when UART testing is enabled.
- Decodes direction and signed position.
- Prints changes over USB serial at 115200 baud.
- Accepts `r` over serial to reset counters.

Build/upload from this folder:

```powershell
platformio run -e pico
platformio run -e pico -t upload
platformio device monitor -b 115200
```

Planned role:

- RP2040 owns fast input capture, debouncing, and button/encoder state.
- CYD owns display, WiFi, OTA, controller communication, and UI state.
- The two boards should communicate over a UART packet protocol once the hardware link is wired.
