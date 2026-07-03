# CYD to RP2040 UART Protocol Notes

Recommended electrical link:

- UART at 3.3V logic.
- Shared GND.
- Start at 115200 baud, move to 230400 or 460800 only if needed.
- RP2040 GP4 TX to ESP32 RX, ESP32 TX to RP2040 GP5 RX.

Initial bring-up protocol:

- Newline-delimited ASCII messages are acceptable while wiring and UI behavior are still moving.
- RP2040 should report input deltas, not raw UI intent.

Example RP2040 to CYD message:

```json
{"type":"input","seq":42,"mpg_delta":-1,"encoder_delta":0,"buttons":5}
```

Recommended production protocol:

- Binary frames over UART using COBS or SLIP framing.
- CRC16 on each frame.
- Sequence number on input frames.
- RP2040 sends deltas and bitmasks.
- CYD sends mode/config messages.

Message types to plan for:

- `HELLO`: firmware and protocol version.
- `INPUT`: sequence, timestamp, MPG delta, UI encoder delta, button bitmask.
- `BUTTON`: sequence, button id, pressed/released.
- `HEARTBEAT`: uptime and status.
- `SET_MODE`: CYD tells RP2040 what input mode the UI is in.
- `CONFIG`: debounce/rate settings if needed later.
