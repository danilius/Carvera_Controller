#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#include <lvgl.h>
#include <TFT_eSPI.h>

#include "AppConfig.h"

namespace {
constexpr uint16_t SCREEN_WIDTH = 320;
constexpr uint16_t SCREEN_HEIGHT = 240;
constexpr uint16_t DRAW_BUF_LINES = 24;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 120;
constexpr uint32_t TOUCH_BUTTON_DEBOUNCE_MS = 250;
constexpr size_t JOG_STEP_COUNT = 4;

#ifndef PENDANT_DISPLAY_TEST
#define PENDANT_DISPLAY_TEST 0
#endif

#ifndef PENDANT_RP_LINK_ENABLE
#define PENDANT_RP_LINK_ENABLE 0
#endif

#ifndef PENDANT_RP_LINK_TX_ENABLE
#define PENDANT_RP_LINK_TX_ENABLE 0
#endif

#ifndef PENDANT_TOUCH_TEST
#define PENDANT_TOUCH_TEST 1
#endif

#ifndef PENDANT_REAL_JOG_ENABLE
#define PENDANT_REAL_JOG_ENABLE 0
#endif

#ifndef TOUCH_CLK
#define TOUCH_CLK 25
#endif

#ifndef TOUCH_DIN
#define TOUCH_DIN 32
#endif

#ifndef TOUCH_DOUT
#define TOUCH_DOUT 39
#endif

#ifndef TOUCH_IRQ
#define TOUCH_IRQ 36
#endif

TFT_eSPI tft = TFT_eSPI();
WiFiServer pendantServer(PENDANT_TCP_PORT);
WiFiClient controllerClient;
HardwareSerial rpSerial(2);

lv_disp_draw_buf_t drawBuf;
lv_color_t drawPixels[SCREEN_WIDTH * DRAW_BUF_LINES];
lv_obj_t* lblStatus = nullptr;
lv_obj_t* lblPos = nullptr;
lv_obj_t* lblJogState = nullptr;
lv_obj_t* lblMpgState = nullptr;
lv_obj_t* lblPendingJog = nullptr;
lv_obj_t* lblHint = nullptr;
lv_obj_t* lblJogButton = nullptr;
lv_obj_t* lblAxisButton = nullptr;
lv_obj_t* lblStepButton = nullptr;

String rxLine;
String rpRxLine;
float mx = 0.0f;
float my = 0.0f;
float mz = 0.0f;

#if PENDANT_RP_LINK_TX_ENABLE
uint32_t rpPingSeq = 0;
uint32_t lastRpPingMs = 0;
#endif
int32_t mpgPosition = 0;
int32_t mpgLastDelta = 0;
bool continuousJogActive = false;
int32_t continuousJogDirection = 0;
uint32_t lastMpgDetentMs = 0;
uint32_t jogMessageSeq = 0;
uint32_t mpgBurstStartMs = 0;
uint16_t mpgBurstDetents = 0;
int32_t mpgBurstDirection = 0;
bool jogEnabled = false;
const char* jogAxis = "X";
const float JOG_STEPS[JOG_STEP_COUNT] = {0.001f, 0.010f, 0.100f, 1.000f};
size_t jogStepIndex = 1;
const float MAX_JOG_COMMAND_MM = 1.000f;
const uint32_t CONTINUOUS_JOG_TIMEOUT_MS = 250;
const uint32_t CONTINUOUS_PROMOTE_WINDOW_MS = 1000;
const uint16_t CONTINUOUS_PROMOTE_DETENTS = 10;
const uint32_t CONTINUOUS_DEMOTE_DETENT_GAP_MS = 250;
uint32_t lastTouchReportMs = 0;
bool touchCalibrating = false;
bool touchCalibrated = true;
bool touchSwapXY = true;
bool touchInvertX = true;
bool touchInvertY = true;
uint16_t touchMinX = 420;
uint16_t touchMaxX = 3763;
uint16_t touchMinY = 234;
uint16_t touchMaxY = 3673;
uint32_t lastTouchButtonMs = 0;
bool wasControllerConnected = false;
bool controllerJogAllowed = false;
String controllerState = "unknown";

bool sendJson(const JsonDocument& doc);

void setLabelText(lv_obj_t* label, const String& text) {
  if (label) {
    lv_label_set_text(label, text.c_str());
  }
}

void refreshPositionLabel() {
  String msg = "X:" + String(mx, 3) + "  Y:" + String(my, 3) + "  Z:" + String(mz, 3);
  setLabelText(lblPos, msg);
}

String jogStepText() {
  return String(JOG_STEPS[jogStepIndex], 3);
}

String jogStateText() {
  String msg = "Jog: ";
  if (!wasControllerConnected) {
    msg += "DISCONNECTED";
  } else {
    msg += jogEnabled ? "ON" : "OFF";
  }
  msg += "   Axis: ";
  msg += jogAxis;
  msg += "   Step: ";
  msg += jogStepText();
  return msg;
}

void styleBottomButton(lv_obj_t* label, bool enabled) {
  if (!label) {
    return;
  }

  lv_obj_t* button = lv_obj_get_parent(label);
  if (!button) {
    return;
  }

  lv_obj_set_style_bg_color(button, lv_color_hex(enabled ? 0x1E5A7A : 0x333333), 0);
  lv_obj_set_style_border_color(button, lv_color_hex(enabled ? 0x68BCE0 : 0x666666), 0);
  lv_obj_set_style_text_color(label, enabled ? lv_color_white() : lv_color_hex(0xAAAAAA), 0);
}

void refreshJogUi() {
  setLabelText(lblJogState, jogStateText());
  setLabelText(lblJogButton, jogEnabled ? "Jog ON" : "Jog OFF");
  setLabelText(lblAxisButton, "Axis " + String(jogAxis));
  setLabelText(lblStepButton, "Step " + jogStepText());
  styleBottomButton(lblJogButton, wasControllerConnected);
  styleBottomButton(lblAxisButton, wasControllerConnected);
  styleBottomButton(lblStepButton, wasControllerConnected);
}

void refreshMpgUi() {
  setLabelText(lblMpgState, "MPG: " + String(mpgPosition) + "   Delta: " + String(mpgLastDelta));
  setLabelText(lblPendingJog, "Pending: no motion");
}

bool isJogAmountAllowed(const String& axis, float amount) {
  const float magnitude = fabs(amount);
  if (axis == "X" || axis == "Y") {
    return magnitude <= MAX_JOG_COMMAND_MM;
  }
  if (axis == "Z") {
    return magnitude <= MAX_JOG_COMMAND_MM;
  }
  return false;
}

float applyAxisDirection(float value) {
  return String(jogAxis) == "Y" ? -value : value;
}

int32_t applyAxisDirection(int32_t value) {
  return String(jogAxis) == "Y" ? -value : value;
}

void resetMpgBurst() {
  mpgBurstStartMs = 0;
  mpgBurstDetents = 0;
  mpgBurstDirection = 0;
}

bool sendJogDelta(int32_t delta) {
  if (!jogEnabled || delta == 0) {
    return false;
  }

  if (!controllerJogAllowed) {
    return false;
  }

  const float amount = static_cast<float>(delta) * JOG_STEPS[jogStepIndex];
#if PENDANT_REAL_JOG_ENABLE
  if (isJogAmountAllowed(String(jogAxis), amount)) {
    const float roundedAmount = roundf(applyAxisDirection(amount) * 1000.0f) / 1000.0f;
    StaticJsonDocument<128> doc;
    doc["type"] = "jog";
    doc["axis"] = jogAxis;
    doc["delta"] = roundedAmount;
    if (!sendJson(doc)) {
      setLabelText(lblHint, "Jog not sent: controller disconnected");
      return false;
    }

    String msg = "SENT JOG ";
    msg += jogAxis;
    msg += " ";
    if (roundedAmount > 0.0f) {
      msg += "+";
    }
    msg += String(roundedAmount, 3);
    setLabelText(lblHint, msg);
    return true;
  }

  String blocked = "Jog blocked: max 1.000";
  Serial.println(blocked);
  setLabelText(lblHint, blocked);
  return false;
#else
  String msg = "DRY JOG ";
  msg += jogAxis;
  msg += " ";
  if (amount > 0.0f) {
    msg += "+";
  }
  msg += String(amount, 3);

  Serial.println(msg);
  setLabelText(lblHint, msg);
  return true;
#endif
}

uint16_t continuousJogFeed() {
  const bool zAxis = String(jogAxis) == "Z";
  switch (jogStepIndex) {
    case 0:
      return zAxis ? 30 : 60;
    case 1:
      return zAxis ? 120 : 300;
    case 2:
      return zAxis ? 300 : 800;
    default:
      return zAxis ? 500 : 1200;
  }
}

bool sendContinuousJogCommand(const char* action, int32_t direction = 0) {
#if PENDANT_REAL_JOG_ENABLE
  if (!controllerClient || !controllerClient.connected()) {
    return false;
  }

  StaticJsonDocument<160> doc;
  doc["type"] = "jog_cont";
  doc["action"] = action;
  doc["axis"] = jogAxis;
  doc["dir"] = applyAxisDirection(direction);
  doc["feed"] = continuousJogFeed();
  doc["seq"] = ++jogMessageSeq;
  if (!sendJson(doc)) {
    return false;
  }

  String msg = "CONT JOG ";
  msg += action;
  if (direction != 0) {
    msg += " ";
    msg += jogAxis;
    msg += applyAxisDirection(direction) > 0 ? "+" : "-";
    msg += " F";
    msg += String(continuousJogFeed());
  }
  setLabelText(lblHint, msg);
  return true;
#else
  return false;
#endif
}

void stopContinuousJog(const char* reason) {
  if (!continuousJogActive) {
    return;
  }

  const bool fullStop = strcmp(reason, "timeout") == 0 ||
                        strcmp(reason, "mpg stop") == 0 ||
                        strcmp(reason, "jog off") == 0 ||
                        strcmp(reason, "disconnect") == 0;
  sendContinuousJogCommand(fullStop ? "full_stop" : "stop");
  continuousJogActive = false;
  continuousJogDirection = 0;
  resetMpgBurst();
  refreshMpgUi();
  setLabelText(lblHint, String("Continuous jog stopped: ") + reason);
}

void startOrRefreshContinuousJog(int32_t delta) {
  if (!jogEnabled || delta == 0 || !wasControllerConnected) {
    return;
  }

  const int32_t direction = delta > 0 ? 1 : -1;
  lastMpgDetentMs = millis();

  if (continuousJogActive && continuousJogDirection == direction) {
    return;
  }

  if (continuousJogActive) {
    stopContinuousJog("direction change");
  }

  if (sendContinuousJogCommand("start", direction)) {
    continuousJogActive = true;
    continuousJogDirection = direction;
  }
}

void serviceContinuousJog() {
  if (!continuousJogActive) {
    return;
  }

  if (!jogEnabled || !wasControllerConnected) {
    stopContinuousJog("not ready");
    return;
  }

  if (millis() - lastMpgDetentMs > CONTINUOUS_JOG_TIMEOUT_MS) {
    stopContinuousJog("timeout");
  }
}

void setJogEnabled(bool enabled) {
  if (enabled && !wasControllerConnected) {
    jogEnabled = false;
    refreshJogUi();
    setLabelText(lblHint, "Controller disconnected");
    return;
  }

  jogEnabled = enabled;
  if (!jogEnabled) {
    stopContinuousJog("jog off");
    resetMpgBurst();
    refreshMpgUi();
  }
  refreshJogUi();
#if PENDANT_REAL_JOG_ENABLE
  setLabelText(lblHint, enabled ? "Jog enabled: max 1.000" : "Jog disabled: no motion");
#else
  setLabelText(lblHint, enabled ? "Jog enabled: display-only" : "Jog disabled: no motion");
#endif
}

void setJogAxis(char axis) {
  stopContinuousJog("axis change");
  resetMpgBurst();
  switch (axis) {
    case 'x':
    case 'X':
      jogAxis = "X";
      break;
    case 'y':
    case 'Y':
      jogAxis = "Y";
      break;
    case 'z':
    case 'Z':
      jogAxis = "Z";
      break;
    default:
      setLabelText(lblHint, "Use: axis x, axis y, or axis z");
      return;
  }

  refreshJogUi();
  setLabelText(lblHint, "Axis set to " + String(jogAxis));
}

void setJogStepIndex(long index) {
  if (index < 0 || index >= static_cast<long>(JOG_STEP_COUNT)) {
    setLabelText(lblHint, "Use: step 0, 1, 2, or 3");
    return;
  }

  stopContinuousJog("step change");
  resetMpgBurst();
  jogStepIndex = static_cast<size_t>(index);
  refreshJogUi();
  setLabelText(lblHint, "Step set to " + jogStepText());
}

void cycleJogAxis() {
  if (String(jogAxis) == "X") {
    setJogAxis('Y');
  } else if (String(jogAxis) == "Y") {
    setJogAxis('Z');
  } else {
    setJogAxis('X');
  }
}

void cycleJogStep() {
  setJogStepIndex(static_cast<long>((jogStepIndex + 1) % JOG_STEP_COUNT));
}

void resetTouchCalibration() {
  touchCalibrating = false;
  touchCalibrated = false;
  touchMinX = 4095;
  touchMaxX = 0;
  touchMinY = 4095;
  touchMaxY = 0;
  setLabelText(lblHint, "Touch calibration reset");
}

void startTouchCalibration() {
  resetTouchCalibration();
  touchCalibrating = true;
  setLabelText(lblHint, "Touch screen corners, then type cal done");
  Serial.println("Touch calibration started. Touch the screen corners and edges, then type: cal done");
}

void finishTouchCalibration() {
  touchCalibrating = false;

  if ((touchMaxX - touchMinX) < 100 || (touchMaxY - touchMinY) < 100) {
    touchCalibrated = false;
    setLabelText(lblHint, "Touch calibration range too small");
    Serial.println("Touch calibration failed: range too small");
    return;
  }

  touchCalibrated = true;
  Serial.print("Touch calibration: x=");
  Serial.print(touchMinX);
  Serial.print("..");
  Serial.print(touchMaxX);
  Serial.print(" y=");
  Serial.print(touchMinY);
  Serial.print("..");
  Serial.println(touchMaxY);
  setLabelText(lblHint, "Touch calibrated");
}

void updateTouchCalibration(uint16_t rawX, uint16_t rawY) {
  if (rawX < touchMinX) {
    touchMinX = rawX;
  }
  if (rawX > touchMaxX) {
    touchMaxX = rawX;
  }
  if (rawY < touchMinY) {
    touchMinY = rawY;
  }
  if (rawY > touchMaxY) {
    touchMaxY = rawY;
  }
}

uint16_t mapTouchValue(uint16_t raw, uint16_t rawMin, uint16_t rawMax, uint16_t screenMax, bool invert) {
  if (rawMax <= rawMin) {
    return 0;
  }

  long mapped = (static_cast<long>(raw) - rawMin) * screenMax / (rawMax - rawMin);
  if (mapped < 0) {
    mapped = 0;
  }
  if (mapped > screenMax) {
    mapped = screenMax;
  }
  if (invert) {
    mapped = screenMax - mapped;
  }
  return static_cast<uint16_t>(mapped);
}

void mapTouchToScreen(uint16_t rawX, uint16_t rawY, uint16_t& screenX, uint16_t& screenY) {
  if (touchSwapXY) {
    screenX = mapTouchValue(rawY, touchMinY, touchMaxY, SCREEN_WIDTH - 1, touchInvertX);
    screenY = mapTouchValue(rawX, touchMinX, touchMaxX, SCREEN_HEIGHT - 1, touchInvertY);
  } else {
    screenX = mapTouchValue(rawX, touchMinX, touchMaxX, SCREEN_WIDTH - 1, touchInvertX);
    screenY = mapTouchValue(rawY, touchMinY, touchMaxY, SCREEN_HEIGHT - 1, touchInvertY);
  }
}

bool handleTouchButton(uint16_t screenX, uint16_t screenY) {
  constexpr uint16_t buttonY = 196;
  constexpr uint16_t buttonH = 40;
  constexpr uint16_t buttonW = 100;
  constexpr uint16_t buttonGap = 5;
  constexpr uint16_t firstX = 5;

  if (screenY < buttonY || screenY >= buttonY + buttonH) {
    return false;
  }

  const uint32_t now = millis();
  if (now - lastTouchButtonMs < TOUCH_BUTTON_DEBOUNCE_MS) {
    return true;
  }
  lastTouchButtonMs = now;

  if (!wasControllerConnected) {
    setLabelText(lblHint, "Controller disconnected");
    return true;
  }

  if (screenX >= firstX && screenX < firstX + buttonW) {
    setJogEnabled(!jogEnabled);
    return true;
  }

  const uint16_t axisX = firstX + buttonW + buttonGap;
  if (screenX >= axisX && screenX < axisX + buttonW) {
    cycleJogAxis();
    return true;
  }

  const uint16_t stepX = axisX + buttonW + buttonGap;
  if (screenX >= stepX && screenX < stepX + buttonW) {
    cycleJogStep();
    return true;
  }

  return false;
}

void updateConnectionUi(bool connected) {
  if (connected) {
    setLabelText(lblStatus, "Controller connected");
    refreshJogUi();
    setLabelText(lblHint, "Ready");
  } else {
    stopContinuousJog("disconnect");
    controllerJogAllowed = false;
    jogEnabled = false;
    controllerState = "disconnected";
    setLabelText(lblStatus, "Controller is disconnected");
    refreshJogUi();
    refreshMpgUi();
    setLabelText(lblHint, "Ready");
  }
}

void flushDisplay(lv_disp_drv_t* disp, const lv_area_t* area, lv_color_t* color_p) {
  const uint32_t w = static_cast<uint32_t>(area->x2 - area->x1 + 1);
  const uint32_t h = static_cast<uint32_t>(area->y2 - area->y1 + 1);

  tft.startWrite();
  tft.setAddrWindow(area->x1, area->y1, w, h);
  tft.pushColors(reinterpret_cast<uint16_t*>(color_p), w * h, true);
  tft.endWrite();

  lv_disp_flush_ready(disp);
}

void runLvglFor(uint32_t ms) {
  const uint32_t startMs = millis();
  do {
    lv_tick_inc(5);
    lv_timer_handler();
    delay(5);
  } while (millis() - startMs < ms);
}

void styleLabel(lv_obj_t* label) {
  lv_obj_set_style_text_color(label, lv_color_white(), 0);
  lv_obj_set_style_text_font(label, &lv_font_montserrat_14, 0);
}

lv_obj_t* createBottomButton(uint16_t x, const char* text) {
  lv_obj_t* button = lv_obj_create(lv_scr_act());
  lv_obj_set_size(button, 100, 40);
  lv_obj_align(button, LV_ALIGN_TOP_LEFT, x, 196);
  lv_obj_clear_flag(button, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scrollbar_mode(button, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_bg_color(button, lv_color_hex(0x1E5A7A), 0);
  lv_obj_set_style_bg_opa(button, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(button, lv_color_hex(0x68BCE0), 0);
  lv_obj_set_style_border_width(button, 1, 0);
  lv_obj_set_style_radius(button, 6, 0);

  lv_obj_t* label = lv_label_create(button);
  styleLabel(label);
  lv_obj_set_width(label, 92);
  lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
  lv_label_set_text(label, text);
  lv_obj_center(label);
  return label;
}

bool sendJson(const JsonDocument& doc) {
  if (!controllerClient || !controllerClient.connected()) {
    return false;
  }

  String out;
  serializeJson(doc, out);
  out += '\n';
  controllerClient.print(out);
  return true;
}

void handleIncomingJson(const String& line) {
  StaticJsonDocument<512> doc;
  const DeserializationError err = deserializeJson(doc, line);
  if (err) {
    return;
  }

  const String type = String(doc["type"] | "");
  if (type == "pos") {
    mx = doc["x"] | mx;
    my = doc["y"] | my;
    mz = doc["z"] | mz;
    refreshPositionLabel();
    return;
  }

  if (type == "machine_state") {
    controllerState = String(doc["state"] | "unknown");
    const bool nextJogAllowed = doc["jog_allowed"] | false;
    if (controllerJogAllowed != nextJogAllowed) {
      controllerJogAllowed = nextJogAllowed;
      refreshJogUi();
    }

    setLabelText(lblStatus, "Controller connected: " + controllerState);
    return;
  }

  if (type == "jog_result") {
    const bool ok = doc["ok"] | false;
    const String command = String(doc["command"] | "");
    const String reason = String(doc["reason"] | "");
    if (ok) {
      setLabelText(lblHint, "Controller accepted " + command);
    } else {
      setLabelText(lblHint, "Jog rejected: " + reason);
    }
    return;
  }

  // During physical jog testing, ignore all controller messages except position.
}

void processSocketRx() {
  while (controllerClient && controllerClient.connected() && controllerClient.available()) {
    char c = static_cast<char>(controllerClient.read());
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (!rxLine.isEmpty()) {
        handleIncomingJson(rxLine);
        rxLine = "";
      }
      continue;
    }
    rxLine += c;
  }
}

uint8_t touchTransfer(uint8_t value) {
  uint8_t in = 0;

  for (uint8_t bit = 0; bit < 8; bit++) {
    digitalWrite(TOUCH_DIN, (value & 0x80) ? HIGH : LOW);
    value <<= 1;

    digitalWrite(TOUCH_CLK, HIGH);
    in <<= 1;
    if (digitalRead(TOUCH_DOUT) == HIGH) {
      in |= 0x01;
    }
    digitalWrite(TOUCH_CLK, LOW);
  }

  return in;
}

uint16_t readTouchAxis(uint8_t command) {
  touchTransfer(command);
  const uint16_t hi = touchTransfer(0x00);
  const uint16_t lo = touchTransfer(0x00);
  return static_cast<uint16_t>(((hi << 8) | lo) >> 3);
}

bool readRawTouch(uint16_t& x, uint16_t& y) {
  if (digitalRead(TOUCH_IRQ) != LOW) {
    return false;
  }

  uint32_t sumX = 0;
  uint32_t sumY = 0;
  constexpr uint8_t TOUCH_SAMPLE_COUNT = 4;

  digitalWrite(TOUCH_CS, LOW);
  delayMicroseconds(2);
  for (uint8_t i = 0; i < TOUCH_SAMPLE_COUNT; i++) {
    sumX += readTouchAxis(0xD0);
    sumY += readTouchAxis(0x90);
  }
  digitalWrite(TOUCH_CS, HIGH);

  x = static_cast<uint16_t>(sumX / TOUCH_SAMPLE_COUNT);
  y = static_cast<uint16_t>(sumY / TOUCH_SAMPLE_COUNT);

  return true;
}

void processTouchTest() {
#if PENDANT_TOUCH_TEST
  uint16_t rawX = 0;
  uint16_t rawY = 0;
  const bool touched = readRawTouch(rawX, rawY);
  const uint32_t now = millis();

  if (!touched || now - lastTouchReportMs < 150) {
    return;
  }

  lastTouchReportMs = now;

  if (touchCalibrating) {
    updateTouchCalibration(rawX, rawY);
    Serial.print("Touch cal raw: x=");
    Serial.print(rawX);
    Serial.print(" y=");
    Serial.print(rawY);
    Serial.print(" range x=");
    Serial.print(touchMinX);
    Serial.print("..");
    Serial.print(touchMaxX);
    Serial.print(" y=");
    Serial.print(touchMinY);
    Serial.print("..");
    Serial.println(touchMaxY);
    setLabelText(lblHint, "Cal raw x:" + String(rawX) + " y:" + String(rawY));
    return;
  }

  if (touchCalibrated) {
    uint16_t screenX = 0;
    uint16_t screenY = 0;
    mapTouchToScreen(rawX, rawY, screenX, screenY);
    const bool handledByButton = handleTouchButton(screenX, screenY);
    Serial.print("Touch: raw x=");
    Serial.print(rawX);
    Serial.print(" y=");
    Serial.print(rawY);
    Serial.print(" screen x=");
    Serial.print(screenX);
    Serial.print(" y=");
    Serial.println(screenY);
    if (handledByButton) {
      return;
    }
    setLabelText(lblHint, "Touch x:" + String(screenX) + " y:" + String(screenY));
    return;
  }

  Serial.print("Touch raw: x=");
  Serial.print(rawX);
  Serial.print(" y=");
  Serial.println(rawY);

  setLabelText(lblHint, "Touch raw x:" + String(rawX) + " y:" + String(rawY));
#endif
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.println("Connecting to WiFi...");
  setLabelText(lblStatus, "Connecting to WiFi...");
  uint32_t startMs = millis();
  while (WiFi.status() != WL_CONNECTED) {
    lv_tick_inc(250);
    lv_timer_handler();
    delay(250);
    if (millis() - startMs > 30000) {
      startMs = millis();
      Serial.println("WiFi retry...");
      setLabelText(lblStatus, "WiFi retry...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
  }

  Serial.print("WiFi connected. IP address: ");
  Serial.println(WiFi.localIP());
  setLabelText(lblStatus, "WiFi connected: " + WiFi.localIP().toString());
  runLvglFor(100);
}

void initOta() {
  ArduinoOTA.setHostname(DEVICE_HOSTNAME);
  ArduinoOTA.begin();
}

void initRpUart() {
#if PENDANT_RP_LINK_ENABLE
  rpSerial.begin(RP_UART_BAUD, SERIAL_8N1, PIN_RP_UART_RX, PIN_RP_UART_TX);
  Serial.print("RP input link enabled. RX GPIO");
  Serial.print(PIN_RP_UART_RX);
  Serial.print(", TX GPIO");
  Serial.print(PIN_RP_UART_TX);
  Serial.print(", baud ");
  Serial.println(RP_UART_BAUD);
  setLabelText(lblHint, "RP input link: waiting...");
#endif
}

void handleMpgEvent(int32_t position, int32_t delta) {
  mpgPosition = position;
  mpgLastDelta = delta;
  refreshJogUi();
  refreshMpgUi();

  if (!jogEnabled || delta == 0) {
    return;
  }

  const uint32_t now = millis();
  const int32_t direction = delta > 0 ? 1 : -1;
  if (continuousJogActive && now - lastMpgDetentMs > CONTINUOUS_DEMOTE_DETENT_GAP_MS) {
    stopContinuousJog("slow detents");
    mpgBurstStartMs = now;
    mpgBurstDetents = 0;
    mpgBurstDirection = direction;
  }

  if (mpgBurstStartMs == 0 ||
      now - mpgBurstStartMs > CONTINUOUS_PROMOTE_WINDOW_MS ||
      mpgBurstDirection != direction) {
    mpgBurstStartMs = now;
    mpgBurstDetents = 0;
    mpgBurstDirection = direction;
  }

  mpgBurstDetents += abs(delta);
  if (jogStepIndex < 3 && (continuousJogActive || mpgBurstDetents >= CONTINUOUS_PROMOTE_DETENTS)) {
    startOrRefreshContinuousJog(delta);
    return;
  }

  if (!sendJogDelta(delta)) {
    setLabelText(lblHint, "Step jog not sent: controller busy");
  }
}

void handleMpgStartEvent(int32_t direction) {
  if (direction == 0) {
    return;
  }

  const int32_t normalizedDirection = direction > 0 ? 1 : -1;
  if (continuousJogActive && continuousJogDirection != normalizedDirection) {
    stopContinuousJog("direction change");
  }

  mpgBurstStartMs = millis();
  mpgBurstDetents = 0;
  mpgBurstDirection = normalizedDirection;
}

void handleMpgStopEvent() {
  stopContinuousJog("mpg stop");
  resetMpgBurst();
  setLabelText(lblHint, "MPG stopped");
}

bool handleRpEvent(const String& line) {
  long position = 0;
  long delta = 0;
  long direction = 0;

  if (sscanf(line.c_str(), "MPG_START %ld", &direction) == 1) {
    handleMpgStartEvent(static_cast<int32_t>(direction));
    return true;
  }

  if (line == "MPG_STOP") {
    handleMpgStopEvent();
    return true;
  }

  if (sscanf(line.c_str(), "MPG_TICK %ld %ld", &position, &delta) == 2) {
    handleMpgEvent(static_cast<int32_t>(position), static_cast<int32_t>(delta));
    return true;
  }

  return false;
}

void handleRpLine(const String& line) {
#if PENDANT_RP_LINK_ENABLE
  Serial.print("RP UART RX: ");
  Serial.println(line);

  if (handleRpEvent(line)) {
    return;
  }

  setLabelText(lblHint, "RP: " + line);
#else
  (void)line;
#endif
}

void processRpLink() {
#if PENDANT_RP_LINK_ENABLE
#if PENDANT_RP_LINK_TX_ENABLE
  const uint32_t now = millis();
  if (now - lastRpPingMs >= 1000) {
    lastRpPingMs = now;
    rpSerial.print("CYD PING ");
    rpSerial.println(++rpPingSeq);
    Serial.print("RP UART TX: CYD PING ");
    Serial.println(rpPingSeq);
  }
#endif

  while (rpSerial.available() > 0) {
    char c = static_cast<char>(rpSerial.read());
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (!rpRxLine.isEmpty()) {
        handleRpLine(rpRxLine);
        rpRxLine = "";
      }
      continue;
    }
    if (rpRxLine.length() < 120) {
      rpRxLine += c;
    } else {
      rpRxLine = "";
    }
  }
#endif
}

void initDisplayHardware() {
  tft.begin();
  if (TFT_BL >= 0) {
    pinMode(TFT_BL, OUTPUT);
    digitalWrite(TFT_BL, TFT_BACKLIGHT_ON);
  }
  tft.setRotation(3);
  tft.fillScreen(TFT_BLACK);

#if PENDANT_TOUCH_TEST
  pinMode(TOUCH_CS, OUTPUT);
  pinMode(TOUCH_CLK, OUTPUT);
  pinMode(TOUCH_DIN, OUTPUT);
  pinMode(TOUCH_DOUT, INPUT);
  pinMode(TOUCH_IRQ, INPUT);
  digitalWrite(TOUCH_CS, HIGH);
  digitalWrite(TOUCH_CLK, LOW);
#endif
}

#if PENDANT_DISPLAY_TEST
void drawDisplaySmokeTest(const String& status) {
  const int w = tft.width();
  const int h = tft.height();
  const int bandH = h / 4;

  tft.fillRect(0, 0, w, bandH, TFT_RED);
  tft.fillRect(0, bandH, w, bandH, TFT_GREEN);
  tft.fillRect(0, bandH * 2, w, bandH, TFT_BLUE);
  tft.fillRect(0, bandH * 3, w, h - (bandH * 3), TFT_BLACK);
  tft.drawRect(0, 0, w, h, TFT_WHITE);

  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(TL_DATUM);
  tft.drawString("CYD display smoke test", 8, bandH * 3 + 8, 2);
  tft.drawString("Rotation: 3 / OTA enabled", 8, bandH * 3 + 28, 2);
  tft.drawString(status, 8, bandH * 3 + 48, 2);
}

void connectWiFiForDisplayTest() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.println("Connecting to WiFi...");
  drawDisplaySmokeTest("Connecting WiFi...");
  uint32_t startMs = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    if (millis() - startMs > 30000) {
      startMs = millis();
      Serial.println("WiFi retry...");
      drawDisplaySmokeTest("WiFi retry...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
  }

  Serial.print("WiFi connected. IP address: ");
  Serial.println(WiFi.localIP());
  drawDisplaySmokeTest("IP: " + WiFi.localIP().toString());
}
#endif

void initLvglUi() {
  lv_init();

  initDisplayHardware();

  lv_disp_draw_buf_init(&drawBuf, drawPixels, nullptr, SCREEN_WIDTH * DRAW_BUF_LINES);

  static lv_disp_drv_t dispDrv;
  lv_disp_drv_init(&dispDrv);
  dispDrv.hor_res = SCREEN_WIDTH;
  dispDrv.ver_res = SCREEN_HEIGHT;
  dispDrv.flush_cb = flushDisplay;
  dispDrv.draw_buf = &drawBuf;
  lv_disp_drv_register(&dispDrv);

  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(0x101820), 0);
  lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);

  lv_obj_t* header = lv_obj_create(lv_scr_act());
  lv_obj_set_size(header, SCREEN_WIDTH, 32);
  lv_obj_align(header, LV_ALIGN_TOP_LEFT, 0, 0);
  lv_obj_set_style_bg_color(header, lv_color_hex(0x0066AA), 0);
  lv_obj_set_style_bg_opa(header, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(header, 0, 0);
  lv_obj_set_style_radius(header, 0, 0);

  lblStatus = lv_label_create(lv_scr_act());
  styleLabel(lblStatus);
  lv_obj_align(lblStatus, LV_ALIGN_TOP_LEFT, 10, 6);
  lv_label_set_long_mode(lblStatus, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(lblStatus, 300);

  lblPos = lv_label_create(lv_scr_act());
  styleLabel(lblPos);
  lv_obj_align(lblPos, LV_ALIGN_TOP_LEFT, 10, 48);
  lv_obj_set_width(lblPos, 300);

  lblJogState = lv_label_create(lv_scr_act());
  styleLabel(lblJogState);
  lv_obj_align(lblJogState, LV_ALIGN_TOP_LEFT, 10, 84);
  lv_label_set_long_mode(lblJogState, LV_LABEL_LONG_CLIP);
  lv_obj_set_width(lblJogState, 300);

  lblMpgState = lv_label_create(lv_scr_act());
  styleLabel(lblMpgState);
  lv_obj_align(lblMpgState, LV_ALIGN_TOP_LEFT, 10, 112);
  lv_label_set_long_mode(lblMpgState, LV_LABEL_LONG_CLIP);
  lv_obj_set_width(lblMpgState, 300);

  lblPendingJog = lv_label_create(lv_scr_act());
  styleLabel(lblPendingJog);
  lv_obj_align(lblPendingJog, LV_ALIGN_TOP_LEFT, 10, 140);
  lv_label_set_long_mode(lblPendingJog, LV_LABEL_LONG_CLIP);
  lv_obj_set_width(lblPendingJog, 300);

  lblHint = lv_label_create(lv_scr_act());
  styleLabel(lblHint);
  lv_obj_align(lblHint, LV_ALIGN_TOP_LEFT, 10, 168);
  lv_label_set_long_mode(lblHint, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(lblHint, 300);

  lblJogButton = createBottomButton(5, "Jog OFF");
  lblAxisButton = createBottomButton(110, "Axis X");
  lblStepButton = createBottomButton(215, "Step 0.010");

  setLabelText(lblStatus, "Booting...");
  refreshPositionLabel();
  refreshJogUi();
  refreshMpgUi();
  setLabelText(lblHint, "Ready");
  runLvglFor(100);
}

void acceptClientIfNeeded() {
  if (controllerClient && controllerClient.connected()) {
    return;
  }

  WiFiClient next = pendantServer.available();
  if (!next) {
    return;
  }

  controllerClient = next;
  rxLine = "";
  updateConnectionUi(true);
}

void updateConnectionState() {
  const bool connected = controllerClient && controllerClient.connected();
  if (connected != wasControllerConnected) {
    wasControllerConnected = connected;
    updateConnectionUi(connected);
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);

#if PENDANT_DISPLAY_TEST
  initDisplayHardware();
  drawDisplaySmokeTest("Booting...");
  connectWiFiForDisplayTest();
  initOta();
  return;
#endif

  initLvglUi();
  initRpUart();
  connectWiFi();
  initOta();

  pendantServer.begin();
  pendantServer.setNoDelay(true);
  updateConnectionState();
}

void loop() {
#if PENDANT_DISPLAY_TEST
  ArduinoOTA.handle();
  static uint32_t lastBlinkMs = 0;
  static bool blink = false;
  if (millis() - lastBlinkMs > 1000) {
    lastBlinkMs = millis();
    blink = !blink;
    tft.fillCircle(tft.width() - 14, tft.height() - 14, 5, blink ? TFT_YELLOW : TFT_BLACK);
  }
  delay(10);
  return;
#endif

  lv_tick_inc(5);
  ArduinoOTA.handle();
  acceptClientIfNeeded();
  processSocketRx();
  processRpLink();
  processTouchTest();
  updateConnectionState();
  serviceContinuousJog();
  lv_timer_handler();
  delay(5);
}
