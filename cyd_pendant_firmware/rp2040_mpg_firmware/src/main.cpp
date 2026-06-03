#include <Arduino.h>
#include "hardware/pio.h"
#include "hardware/pio_instructions.h"

constexpr uint8_t ENC_A_PIN = 2;
constexpr uint8_t ENC_B_PIN = 3;
constexpr uint8_t CYD_UART_TX_PIN = 4;  // RP GP4 transmits to CYD RX.
constexpr uint8_t CYD_UART_RX_PIN = 5;  // RP GP5 receives from CYD TX.
constexpr uint8_t UI_ENC_S1_PIN = 6;
constexpr uint8_t UI_ENC_S2_PIN = 7;
constexpr uint8_t UI_ENC_KEY_PIN = 8;
constexpr uint32_t CYD_UART_BAUD = 115200;
constexpr int32_t MPG_NUMBER_MOD = 100;
constexpr uint32_t ENCODER_SERVICE_SPIN_MS = 2;
constexpr uint32_t MPG_STOP_TIMEOUT_MS = 120;
constexpr uint32_t UI_ENC_KEY_DEBOUNCE_MS = 60;

#ifndef RP_HEARTBEAT_SERIAL
#define RP_HEARTBEAT_SERIAL 0
#endif

#ifndef RP_CYD_UART_ENABLE
#define RP_CYD_UART_ENABLE 0
#endif

#ifndef RP_CYD_UART_TX_ENABLE
#define RP_CYD_UART_TX_ENABLE 0
#endif

#ifndef RP_CYD_UART_RX_ENABLE
#define RP_CYD_UART_RX_ENABLE 0
#endif

#ifndef RP_DEBUG_MPG_SERIAL
#define RP_DEBUG_MPG_SERIAL 0
#endif

static const uint16_t QUAD_CAPTURE_PROGRAM_INSTRUCTIONS[] = {
  pio_encode_mov(pio_x, pio_pins),
  pio_encode_jmp_x_ne_y(3),
  pio_encode_jmp(0),
  pio_encode_mov(pio_isr, pio_x),
  pio_encode_push(false, false),
  pio_encode_mov(pio_y, pio_x),
  pio_encode_jmp(0)
};

static const pio_program_t QUAD_CAPTURE_PROGRAM = {
  .instructions = QUAD_CAPTURE_PROGRAM_INSTRUCTIONS,
  .length = 7,
  .origin = -1
};

PIO encoderPio = pio0;
uint encoderSm = 0;

volatile uint32_t edgeCount = 0;
volatile int32_t signedCount = 0;
volatile int8_t lastDelta = 0;
volatile uint8_t lastState = 0;
volatile int32_t detentCount = 0;
volatile int8_t detentRemainder = 0;
volatile int8_t lastDetentDelta = 0;
uint8_t uiEncoderLastState = 0;
int8_t uiEncoderRemainder = 0;
bool uiEncoderKeyLast = true;
bool uiEncoderKeyStable = true;
uint32_t uiEncoderKeyChangedMs = 0;

#if RP_CYD_UART_ENABLE
arduino::UART* cydLink = nullptr;
String cydRxLine;
#endif

const int8_t QUAD_TABLE[16] = {
  0, -1, +1,  0,
  +1, 0,  0, -1,
  -1, 0,  0, +1,
  0, +1, -1,  0
};

void initPioEncoder() {
  uint offset = pio_add_program(encoderPio, &QUAD_CAPTURE_PROGRAM);

  pio_gpio_init(encoderPio, ENC_A_PIN);
  pio_gpio_init(encoderPio, ENC_B_PIN);
  pio_sm_set_consecutive_pindirs(encoderPio, encoderSm, ENC_A_PIN, 2, false);

  pio_sm_config cfg = pio_get_default_sm_config();
  sm_config_set_clkdiv(&cfg, 1.0f);
  sm_config_set_in_pins(&cfg, 0);

  pio_sm_init(encoderPio, encoderSm, offset, &cfg);
  pio_sm_set_enabled(encoderPio, encoderSm, true);
}

void servicePioEncoder() {
  while (!pio_sm_is_rx_fifo_empty(encoderPio, encoderSm)) {
    uint32_t rawPins = pio_sm_get(encoderPio, encoderSm);
    uint8_t a = (uint8_t)((rawPins >> ENC_A_PIN) & 0x1u);
    uint8_t b = (uint8_t)((rawPins >> ENC_B_PIN) & 0x1u);
    uint8_t newState = (uint8_t)((a << 1) | b);

    uint8_t idx = (uint8_t)((lastState << 2) | newState);
    int8_t quadDelta = QUAD_TABLE[idx];

    if (quadDelta != 0) {
      int8_t delta = (int8_t)(-quadDelta);
      edgeCount++;
      signedCount += delta;
      lastDelta = delta;
      detentRemainder += delta;
      if (detentRemainder >= 4) {
        detentCount++;
        lastDetentDelta = 1;
        detentRemainder = 0;
      } else if (detentRemainder <= -4) {
        detentCount--;
        lastDetentDelta = -1;
        detentRemainder = 0;
      }
    }

    lastState = newState;
  }
}

void serviceEncoderFor(uint32_t durationMs) {
  const uint32_t startMs = millis();
  do {
    servicePioEncoder();
  } while (millis() - startMs < durationMs);
}

void resetCounters() {
  noInterrupts();
  edgeCount = 0;
  signedCount = 0;
  lastDelta = 0;
  detentCount = 0;
  detentRemainder = 0;
  lastDetentDelta = 0;
  lastState = ((uint8_t)digitalRead(ENC_A_PIN) << 1) | (uint8_t)digitalRead(ENC_B_PIN);
  interrupts();
}

void processSerialCommands(uint32_t& lastReportedEdges, int32_t& lastReportedDetent) {
  static char cmdBuf[16];
  static uint8_t cmdLen = 0;

  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r' || c == '\n') {
      if (cmdLen > 0) {
        cmdBuf[cmdLen] = '\0';

        if ((cmdBuf[0] == 'r' || cmdBuf[0] == 'R') && cmdBuf[1] == '\0') {
          resetCounters();
          lastReportedEdges = 0;
          lastReportedDetent = 0;
          Serial.println("Counters reset. Position=0");
        } else {
          Serial.println("Unknown command. Use: r");
        }
      }
      cmdLen = 0;
      continue;
    }

    if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

int32_t wrapNumber0To99(int32_t value) {
  int32_t out = value % MPG_NUMBER_MOD;
  if (out < 0) {
    out += MPG_NUMBER_MOD;
  }
  return out;
}

void setup() {
  Serial.begin(115200);
  delay(800);

#if RP_CYD_UART_ENABLE
  cydLink = new arduino::UART(
    digitalPinToPinName(CYD_UART_TX_PIN),
    digitalPinToPinName(CYD_UART_RX_PIN)
  );
  cydLink->begin(CYD_UART_BAUD);
#endif

  pinMode(ENC_A_PIN, INPUT_PULLUP);
  pinMode(ENC_B_PIN, INPUT_PULLUP);
  pinMode(UI_ENC_S1_PIN, INPUT_PULLUP);
  pinMode(UI_ENC_S2_PIN, INPUT_PULLUP);
  pinMode(UI_ENC_KEY_PIN, INPUT_PULLUP);

  lastState = ((uint8_t)digitalRead(ENC_A_PIN) << 1) | (uint8_t)digitalRead(ENC_B_PIN);
  uiEncoderLastState = ((uint8_t)digitalRead(UI_ENC_S1_PIN) << 1) | (uint8_t)digitalRead(UI_ENC_S2_PIN);
  uiEncoderKeyLast = digitalRead(UI_ENC_KEY_PIN) == HIGH;
  uiEncoderKeyStable = uiEncoderKeyLast;
  initPioEncoder();

  Serial.println("\nRP2040 MPG test running");
  Serial.println("Pins: A=GPIO2, B=GPIO3 (INPUT_PULLUP)");
  Serial.println("UI encoder: S1=GPIO6, S2=GPIO7, Key=GPIO8");
  Serial.println("Mode: PIO capture + quadrature decode");
  Serial.println("Type: r + Enter to reset counters");
#if RP_CYD_UART_ENABLE
  Serial.print("CYD UART link enabled: RX GP");
  Serial.print(CYD_UART_RX_PIN);
  Serial.print(", TX GP");
  Serial.print(CYD_UART_TX_PIN);
  Serial.print(", baud ");
  Serial.println(CYD_UART_BAUD);
#endif
}

void sendCydLine(const String& msg) {
#if RP_CYD_UART_ENABLE && RP_CYD_UART_TX_ENABLE
  if (!cydLink) {
    return;
  }

  String out = msg + "\n";
  cydLink->write(reinterpret_cast<const uint8_t*>(out.c_str()), out.length());
#else
  (void)msg;
#endif
}

void sendMpgStart(int32_t direction) {
  String msg = "MPG_START ";
  msg += String(direction);
  sendCydLine(msg);
}

void sendMpgTick(int32_t position, int32_t delta) {
  String msg = "MPG_TICK ";
  msg += String(position);
  msg += " ";
  msg += String(delta);
  sendCydLine(msg);
}

void sendMpgStop() {
  sendCydLine("MPG_STOP");
}

void sendUiEncoderTick(int32_t delta) {
  String msg = "ENC_TICK ";
  msg += String(delta);
  sendCydLine(msg);
}

void sendUiEncoderPress() {
  sendCydLine("ENC_PRESS");
}

void serviceUiEncoder() {
  uint8_t s1 = (uint8_t)digitalRead(UI_ENC_S1_PIN);
  uint8_t s2 = (uint8_t)digitalRead(UI_ENC_S2_PIN);
  uint8_t newState = (uint8_t)((s1 << 1) | s2);
  if (newState == uiEncoderLastState) {
    return;
  }

  uint8_t idx = (uint8_t)((uiEncoderLastState << 2) | newState);
  int8_t quadDelta = QUAD_TABLE[idx];
  uiEncoderLastState = newState;

  if (quadDelta == 0) {
    return;
  }

  uiEncoderRemainder += quadDelta;
  if (uiEncoderRemainder >= 4) {
    uiEncoderRemainder = 0;
    sendUiEncoderTick(1);
  } else if (uiEncoderRemainder <= -4) {
    uiEncoderRemainder = 0;
    sendUiEncoderTick(-1);
  }
}

void serviceUiEncoderKey() {
  const bool keyNow = digitalRead(UI_ENC_KEY_PIN) == HIGH;
  const uint32_t now = millis();

  if (keyNow != uiEncoderKeyLast) {
    uiEncoderKeyLast = keyNow;
    uiEncoderKeyChangedMs = now;
  }

  if (keyNow != uiEncoderKeyStable && now - uiEncoderKeyChangedMs >= UI_ENC_KEY_DEBOUNCE_MS) {
    uiEncoderKeyStable = keyNow;
    if (!uiEncoderKeyStable) {
      sendUiEncoderPress();
    }
  }
}

void processCydLinkRx() {
#if RP_CYD_UART_ENABLE && RP_CYD_UART_RX_ENABLE
  if (!cydLink) {
    return;
  }

  while (cydLink->available() > 0) {
    char c = (char)cydLink->read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (!cydRxLine.isEmpty()) {
        Serial.print("CYD UART RX: ");
        Serial.println(cydRxLine);
        cydRxLine = "";
      }
      continue;
    }
    if (cydRxLine.length() < 120) {
      cydRxLine += c;
    } else {
      cydRxLine = "";
    }
  }
#endif
}

void loop() {
  static uint32_t lastReportedEdges = 0;
  static int32_t lastReportedDetent = 0;
  static uint32_t lastHeartbeatMs = 0;
  static bool mpgMoving = false;
  static int32_t mpgDirection = 0;
  static uint32_t lastDetentMs = 0;

  servicePioEncoder();
  serviceUiEncoder();
  serviceUiEncoderKey();
  processSerialCommands(lastReportedEdges, lastReportedDetent);
  servicePioEncoder();
  serviceUiEncoder();
  serviceUiEncoderKey();
  processCydLinkRx();
  servicePioEncoder();
  serviceUiEncoder();
  serviceUiEncoderKey();

  uint32_t edgesSnapshot;
  int32_t rawPositionSnapshot;
  int32_t detentSnapshot;
  noInterrupts();
  edgesSnapshot = edgeCount;
  rawPositionSnapshot = signedCount;
  detentSnapshot = detentCount;
  interrupts();

#if RP_HEARTBEAT_SERIAL
  if (millis() - lastHeartbeatMs >= 2000) {
    lastHeartbeatMs = millis();
    Serial.print("RP alive | Edges: ");
    Serial.print(edgesSnapshot);
    Serial.print(" | Raw: ");
    Serial.print(rawPositionSnapshot);
    Serial.print(" | Detents: ");
    Serial.println(detentSnapshot);
  }
#else
  (void)lastHeartbeatMs;
#endif

  if (detentSnapshot != lastReportedDetent) {
    const uint32_t now = millis();
    int32_t detentDelta = detentSnapshot - lastReportedDetent;
    const int32_t direction = detentDelta > 0 ? 1 : -1;
    if (!mpgMoving || mpgDirection != direction) {
      if (mpgMoving) {
        sendMpgStop();
      }
      mpgMoving = true;
      mpgDirection = direction;
      sendMpgStart(direction);
    }

    sendMpgTick(detentSnapshot, detentDelta);
    lastDetentMs = now;
    serviceEncoderFor(ENCODER_SERVICE_SPIN_MS);

#if RP_DEBUG_MPG_SERIAL
    int32_t numberSnapshot = wrapNumber0To99(detentSnapshot);
    Serial.print("Edges: ");
    Serial.print(edgesSnapshot);
    Serial.print(" | Dir: ");
    Serial.print((detentDelta > 0) ? "CW" : "CCW");
    Serial.print(" | Number(0-99): ");
    Serial.print(numberSnapshot);
    Serial.print(" | Position: ");
    Serial.print(detentSnapshot);
    Serial.print(" | Raw: ");
    Serial.println(rawPositionSnapshot);
#endif
    lastReportedEdges = edgesSnapshot;
    lastReportedDetent = detentSnapshot;
  }

  if (mpgMoving && millis() - lastDetentMs > MPG_STOP_TIMEOUT_MS) {
    mpgMoving = false;
    mpgDirection = 0;
    sendMpgStop();
  }
}
