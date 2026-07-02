#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
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
constexpr size_t JOG_STEP_COUNT = 5;

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

#ifndef PENDANT_REAL_PROBE_ENABLE
#define PENDANT_REAL_PROBE_ENABLE 0
#endif

#ifndef PENDANT_REAL_ATC_ENABLE
#define PENDANT_REAL_ATC_ENABLE 0
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
Preferences preferences;

lv_disp_draw_buf_t drawBuf;
lv_color_t drawPixels[SCREEN_WIDTH * DRAW_BUF_LINES];
lv_obj_t* headerBar = nullptr;
lv_obj_t* lblStatus = nullptr;
lv_obj_t* lblHint = nullptr;
lv_obj_t* lblJogButton = nullptr;
lv_obj_t* lblStepButton = nullptr;
lv_obj_t* lblModeButton = nullptr;
lv_obj_t* lblCoordButton = nullptr;
lv_obj_t* lblAxisX = nullptr;
lv_obj_t* lblAxisY = nullptr;
lv_obj_t* lblAxisZ = nullptr;
lv_obj_t* lblMenuButton = nullptr;
lv_obj_t* lblProbeValue1 = nullptr;
lv_obj_t* lblProbeValue2 = nullptr;
lv_obj_t* lblProbeValue3 = nullptr;
lv_obj_t* lblEditValue = nullptr;
lv_obj_t* lblRuntimeFeed = nullptr;
lv_obj_t* lblRuntimeSpindle = nullptr;
lv_obj_t* lblRuntimePause = nullptr;
lv_obj_t* lblRuntimeAir = nullptr;

String rxLine;
String rpRxLine;
float mx = 0.0f;
float my = 0.0f;
float mz = 0.0f;
float wx = 0.0f;
float wy = 0.0f;
float wz = 0.0f;

enum class UiPage {
  Home,
  RuntimeHome,
  MainMenu,
  PositionMenu,
  SetOriginMenu,
  AtcMenu,
  MacroMenu,
  ProbeMenu,
  ProbeSingle,
  ProbeBore,
  ProbeBoss,
  ProbeEdit,
  ProbeRunning,
};

enum class ProbeField {
  SingleDistance,
  BoreX,
  BoreY,
  BossX,
  BossY,
  BossDepth,
};

enum class ButtonStyle {
  Normal,
  Back,
  Save,
  RuntimeNormal,
  RuntimeSelected,
  Warning,
  Danger,
  AirOn,
  CoordWork,
};

enum class RuntimeTarget {
  Feed,
  Spindle,
};

UiPage currentPage = UiPage::Home;
UiPage editReturnPage = UiPage::ProbeSingle;
UiPage probeReturnPage = UiPage::ProbeMenu;
ProbeField editField = ProbeField::SingleDistance;
float singleProbeDistance = 10.0f;
float boreProbeX = 10.0f;
float boreProbeY = 10.0f;
float bossProbeX = 10.0f;
float bossProbeY = 10.0f;
float bossProbeDepth = 2.0f;

#if PENDANT_RP_LINK_TX_ENABLE
uint32_t rpPingSeq = 0;
uint32_t lastRpPingMs = 0;
#endif
bool continuousJogActive = false;
int32_t continuousJogDirection = 0;
uint32_t lastMpgDetentMs = 0;
uint32_t jogMessageSeq = 0;
uint32_t mpgBurstStartMs = 0;
uint16_t mpgBurstDetents = 0;
int32_t mpgBurstDirection = 0;
int32_t pendingStepJogDetents = 0;
uint32_t lastStepJogSendMs = 0;
bool jogEnabled = false;
bool jogContinuousMode = false;
bool showWorkCoordinates = false;
const char* jogAxis = "X";
const float JOG_STEPS[JOG_STEP_COUNT] = {0.001f, 0.010f, 0.100f, 1.000f, 2.000f};
size_t jogStepIndex = 1;
const float MAX_JOG_COMMAND_MM = 2.000f;
const uint32_t CONTINUOUS_JOG_TIMEOUT_MS = 250;
const uint32_t STEP_JOG_COALESCE_MS = 60;
const int32_t STEP_JOG_MAX_PENDING_DETENTS = 20;
constexpr uint16_t BOTTOM_BUTTON_Y = 196;
constexpr uint16_t BOTTOM_BUTTON_H = 40;
constexpr uint16_t BOTTOM_BUTTON_W = 100;
constexpr uint16_t BOTTOM_BUTTON_GAP = 5;
constexpr uint16_t BOTTOM_BUTTON_FIRST_X = 5;
constexpr uint16_t AXIS_TILE_X = 10;
constexpr uint16_t AXIS_TILE_Y = 48;
constexpr uint16_t AXIS_TILE_W = 140;
constexpr uint16_t AXIS_TILE_H = 40;
constexpr uint16_t AXIS_TILE_GAP = 8;
constexpr uint32_t BACK_LONG_PRESS_MS = 900;
uint32_t lastTouchReportMs = 0;
bool editSwipeTracking = false;
uint16_t editSwipeStartX = 0;
uint16_t editSwipeLastX = 0;
bool backPressTracking = false;
bool backLongPressHandled = false;
bool touchCapturedUntilRelease = false;
bool runtimeStopTracking = false;
bool runtimeStopSent = false;
uint32_t runtimeStopStartMs = 0;
bool probeCommandActive = false;
bool probeMotionSeen = false;
uint32_t backPressStartMs = 0;
UiPage backPressPage = UiPage::Home;
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
String controllerActivity = "idle";
String toolLabel = "No Tool";
String targetToolLabel = "No Tool";
bool programRunning = false;
bool programPaused = false;
int feedOverridePct = 100;
int spindleOverridePct = 100;
bool airOn = false;
float playedPercent = 0.0f;
RuntimeTarget runtimeTarget = RuntimeTarget::Feed;
const uint8_t MAX_MACROS = 10;
const uint8_t MAX_VISIBLE_MACROS = 8;
uint8_t macroCount = 0;
int macroIds[MAX_MACROS] = {0};
String macroNames[MAX_MACROS];

bool sendJson(const JsonDocument& doc);
bool runtimeActive();
void sendGcodeCommand(const String& line);
void openPage(UiPage page);
void renderPage();

void setLabelText(lv_obj_t* label, const String& text) {
  if (label) {
    lv_label_set_text(label, text.c_str());
  }
}

String probeValueText(const char* label, float value) {
  return String(label) + " " + String(value, 1);
}

float& probeFieldValue(ProbeField field) {
  switch (field) {
    case ProbeField::SingleDistance:
      return singleProbeDistance;
    case ProbeField::BoreX:
      return boreProbeX;
    case ProbeField::BoreY:
      return boreProbeY;
    case ProbeField::BossX:
      return bossProbeX;
    case ProbeField::BossY:
      return bossProbeY;
    case ProbeField::BossDepth:
      return bossProbeDepth;
  }
  return singleProbeDistance;
}

const char* probeFieldKey(ProbeField field) {
  switch (field) {
    case ProbeField::SingleDistance:
      return "single_d";
    case ProbeField::BoreX:
      return "bore_x";
    case ProbeField::BoreY:
      return "bore_y";
    case ProbeField::BossX:
      return "boss_x";
    case ProbeField::BossY:
      return "boss_y";
    case ProbeField::BossDepth:
      return "boss_e";
  }
  return "single_d";
}

String probeFieldLabel(ProbeField field) {
  switch (field) {
    case ProbeField::SingleDistance:
      return "Distance";
    case ProbeField::BoreX:
      return "Bore X";
    case ProbeField::BoreY:
      return "Bore Y";
    case ProbeField::BossX:
      return "Boss X";
    case ProbeField::BossY:
      return "Boss Y";
    case ProbeField::BossDepth:
      return "Depth";
  }
  return "Distance";
}

void loadProbeSettings() {
  preferences.begin("probe", false);
  singleProbeDistance = preferences.getFloat(probeFieldKey(ProbeField::SingleDistance), singleProbeDistance);
  boreProbeX = preferences.getFloat(probeFieldKey(ProbeField::BoreX), boreProbeX);
  boreProbeY = preferences.getFloat(probeFieldKey(ProbeField::BoreY), boreProbeY);
  bossProbeX = preferences.getFloat(probeFieldKey(ProbeField::BossX), bossProbeX);
  bossProbeY = preferences.getFloat(probeFieldKey(ProbeField::BossY), bossProbeY);
  bossProbeDepth = preferences.getFloat(probeFieldKey(ProbeField::BossDepth), bossProbeDepth);
}

void saveProbeField(ProbeField field) {
  preferences.putFloat(probeFieldKey(field), probeFieldValue(field));
}

String localToolLabel(int32_t tool) {
  if (tool == 0) {
    return "Probe";
  }
  if (tool == 8888) {
    return "Laser";
  }
  if (tool >= 999990 && tool <= 999999) {
    return "3D Probe";
  }
  if (tool > 0) {
    return "T" + String(tool);
  }
  return "No Tool";
}

String activityLabel(const String& activity) {
  if (activity == "idle") {
    return "";
  }
  if (activity == "running_gcode" || activity == "running") {
    return "RUNNING";
  }
  if (activity == "changing_tool") {
    return "TOOL";
  }
  if (activity == "probing") {
    return "PROBING";
  }
  if (activity == "leveling") {
    return "LEVELING";
  }
  if (activity == "alarm") {
    return "ALARM";
  }
  if (activity == "paused") {
    return "PAUSED";
  }
  if (activity == "holding") {
    return "HOLD";
  }
  if (activity == "waiting") {
    return "WAIT";
  }
  return activity;
}

void refreshTopBar() {
  if (!lblStatus) {
    return;
  }

  String text;
  uint32_t color = 0x0066AA;
  if (!wasControllerConnected) {
    text = "DISCONNECTED";
    color = 0x4A4A4A;
  } else {
    text = toolLabel;
    const String activity = activityLabel(controllerActivity);
    if (activity.length() > 0) {
      text += "   ";
      text += activity;
      color = controllerActivity == "alarm" ? 0xAA2222 : 0x9A6A00;
    }
    if (runtimeActive()) {
      text = toolLabel + (programPaused ? "   PAUSED" : "   RUN");
      if (playedPercent > 0.0f) {
        text += "   ";
        text += String(playedPercent, 0);
        text += "%";
      }
      color = programPaused ? 0xB87800 : 0x0066AA;
    }
    if (controllerActivity == "changing_tool" && targetToolLabel.length() > 0) {
      text = toolLabel + " -> " + targetToolLabel;
    }
  }

  if (headerBar) {
    lv_obj_set_style_bg_color(headerBar, lv_color_hex(color), 0);
  }
  setLabelText(lblStatus, text);
}

void refreshPositionLabel() {
  const float x = showWorkCoordinates ? wx : mx;
  const float y = showWorkCoordinates ? wy : my;
  const float z = showWorkCoordinates ? wz : mz;
  setLabelText(lblAxisX, "X     " + String(x, 3));
  setLabelText(lblAxisY, "Y     " + String(y, 3));
  setLabelText(lblAxisZ, "Z     " + String(z, 3));
}

String jogStepText() {
  return String(JOG_STEPS[jogStepIndex], 3);
}

lv_color_t axisColor(char axis) {
  switch (axis) {
    case 'X':
      return lv_color_hex(0xFF4D4D);
    case 'Y':
      return lv_color_hex(0x45D16F);
    case 'Z':
      return lv_color_hex(0x4DA3FF);
    default:
      return lv_color_white();
  }
}

lv_color_t axisSelectedBg(char axis) {
  switch (axis) {
    case 'X':
      return lv_color_hex(0x5A1E1E);
    case 'Y':
      return lv_color_hex(0x1E4A2C);
    case 'Z':
      return lv_color_hex(0x1E365A);
    default:
      return lv_color_hex(0x1C2730);
  }
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

void styleAxisTile(lv_obj_t* label, char axis) {
  if (!label) {
    return;
  }

  lv_obj_t* tile = lv_obj_get_parent(label);
  if (!tile) {
    return;
  }

  const bool selected = String(jogAxis) == String(axis);
  const bool active = jogEnabled && wasControllerConnected;
  lv_obj_set_style_bg_color(tile, selected && active ? axisSelectedBg(axis) : lv_color_hex(0x17212A), 0);
  lv_obj_set_style_border_color(tile, selected && active ? axisColor(axis) : lv_color_hex(0x46515C), 0);
  lv_obj_set_style_border_width(tile, selected ? 3 : 1, 0);
  lv_obj_set_style_text_color(label, active ? axisColor(axis) : lv_color_hex(0x888888), 0);
}

void refreshAxisTiles() {
  styleAxisTile(lblAxisX, 'X');
  styleAxisTile(lblAxisY, 'Y');
  styleAxisTile(lblAxisZ, 'Z');
}

void refreshJogUi() {
  setLabelText(lblJogButton, jogEnabled ? "Jog ON" : "Jog OFF");
  setLabelText(lblStepButton, jogStepText());
  setLabelText(lblModeButton, jogContinuousMode ? "Cont" : "Step");
  styleBottomButton(lblJogButton, wasControllerConnected);
  styleBottomButton(lblStepButton, wasControllerConnected);
  styleBottomButton(lblModeButton, wasControllerConnected);
  refreshAxisTiles();
}

void refreshCoordinateButton() {
  setLabelText(lblCoordButton, showWorkCoordinates ? "WORK" : "MACHINE");
}

void toggleCoordinateDisplay() {
  showWorkCoordinates = !showWorkCoordinates;
  refreshPositionLabel();
  renderPage();
  setLabelText(lblHint, showWorkCoordinates ? "Showing work coordinates" : "Showing machine coordinates");
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
  pendingStepJogDetents = 0;
  lastStepJogSendMs = 0;
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

    return true;
  }

  String blocked = "Jog blocked: max 2.000";
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

  setLabelText(lblHint, msg);
  return true;
#endif
}

void queueStepJogDelta(int32_t delta) {
  if (delta == 0) {
    return;
  }

  pendingStepJogDetents += delta;
  if (pendingStepJogDetents > STEP_JOG_MAX_PENDING_DETENTS) {
    pendingStepJogDetents = STEP_JOG_MAX_PENDING_DETENTS;
  } else if (pendingStepJogDetents < -STEP_JOG_MAX_PENDING_DETENTS) {
    pendingStepJogDetents = -STEP_JOG_MAX_PENDING_DETENTS;
  }
}

void servicePendingStepJog(bool force = false) {
  if (pendingStepJogDetents == 0) {
    return;
  }

  if (!jogEnabled || !controllerJogAllowed || !wasControllerConnected || currentPage != UiPage::Home) {
    pendingStepJogDetents = 0;
    return;
  }

  const uint32_t now = millis();
  if (!force && lastStepJogSendMs != 0 && now - lastStepJogSendMs < STEP_JOG_COALESCE_MS) {
    return;
  }

  int32_t maxDetentsPerCommand = static_cast<int32_t>(floorf(MAX_JOG_COMMAND_MM / JOG_STEPS[jogStepIndex]));
  if (maxDetentsPerCommand < 1) {
    maxDetentsPerCommand = 1;
  }
  int32_t detentsToSend = pendingStepJogDetents;
  if (detentsToSend > maxDetentsPerCommand) {
    detentsToSend = maxDetentsPerCommand;
  } else if (detentsToSend < -maxDetentsPerCommand) {
    detentsToSend = -maxDetentsPerCommand;
  }

  if (sendJogDelta(detentsToSend)) {
    pendingStepJogDetents -= detentsToSend;
    lastStepJogSendMs = now;
  } else {
    pendingStepJogDetents = 0;
    setLabelText(lblHint, "Step jog not sent: controller busy");
  }
}

void sendGcodeCommand(const String& line) {
#if PENDANT_REAL_PROBE_ENABLE
  probeReturnPage = currentPage;
  probeCommandActive = true;
  probeMotionSeen = false;
  StaticJsonDocument<128> doc;
  doc["type"] = "gcode";
  doc["line"] = line;
  if (!sendJson(doc)) {
    probeCommandActive = false;
    setLabelText(lblHint, "Probe not sent: disconnected");
  } else {
    openPage(UiPage::ProbeRunning);
  }
#else
  setLabelText(lblHint, "DRY PROBE: " + line);
#endif
}

void sendProbeCancelCommand() {
  StaticJsonDocument<96> doc;
  doc["type"] = "runtime";
  doc["action"] = "probe_cancel";
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Cancel not sent");
  } else {
    probeMotionSeen = true;
    setLabelText(lblHint, "Cancel sent");
  }
}

void sendToolChangeCommand(int32_t tool) {
#if PENDANT_REAL_ATC_ENABLE
  setLabelText(lblStatus, "Request " + localToolLabel(tool));
  StaticJsonDocument<128> doc;
  doc["type"] = "tool";
  doc["action"] = "change";
  doc["tool"] = tool;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Tool command not sent");
  }
#else
  setLabelText(lblHint, "DRY TOOL: " + localToolLabel(tool));
#endif
}

void sendToolDropCommand() {
#if PENDANT_REAL_ATC_ENABLE
  setLabelText(lblStatus, "Request Drop");
  StaticJsonDocument<96> doc;
  doc["type"] = "tool";
  doc["action"] = "drop";
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Drop command not sent");
  }
#else
  setLabelText(lblHint, "DRY TOOL: Drop");
#endif
}

void sendToolClampCommand(bool clamp) {
#if PENDANT_REAL_ATC_ENABLE
  setLabelText(lblStatus, clamp ? "Request Clamp" : "Request Unclamp");
  StaticJsonDocument<96> doc;
  doc["type"] = "tool";
  doc["action"] = clamp ? "clamp" : "unclamp";
  if (!sendJson(doc)) {
    setLabelText(lblHint, clamp ? "Clamp command not sent" : "Unclamp command not sent");
  }
#else
  setLabelText(lblHint, clamp ? "DRY TOOL: Clamp" : "DRY TOOL: Unclamp");
#endif
}

void requestMacroList() {
  StaticJsonDocument<64> doc;
  doc["type"] = "macro_query";
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Macros not available: disconnected");
  }
}

void sendMacroRunCommand(uint8_t index) {
  if (index >= macroCount) {
    return;
  }

  setLabelText(lblHint, "Run macro: " + macroNames[index]);
  StaticJsonDocument<96> doc;
  doc["type"] = "macro";
  doc["action"] = "run";
  doc["id"] = macroIds[index];
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Macro not sent: disconnected");
  }
}

bool runtimeActive() {
  return programRunning || programPaused;
}

void sendRuntimeCommand(const String& action) {
  StaticJsonDocument<128> doc;
  doc["type"] = "runtime";
  doc["action"] = action;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Runtime command not sent");
  }
}

void sendRuntimeOverride(int delta, bool reset = false) {
  StaticJsonDocument<160> doc;
  doc["type"] = "runtime";
  doc["action"] = "override";
  doc["target"] = runtimeTarget == RuntimeTarget::Feed ? "feed" : "spindle";
  doc["delta"] = delta;
  doc["reset"] = reset;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Override not sent");
  }
}

void sendRuntimeAirToggle() {
  StaticJsonDocument<96> doc;
  doc["type"] = "runtime";
  doc["action"] = "air";
  doc["on"] = !airOn;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Air command not sent");
  }
}

void sendPositionGotoCommand(const char* target) {
  StaticJsonDocument<128> doc;
  doc["type"] = "position";
  doc["action"] = "goto";
  doc["target"] = target;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Position command not sent");
  } else {
    setLabelText(lblHint, "Position command sent");
  }
}

void sendSetOriginCommand(const char* axes) {
  StaticJsonDocument<128> doc;
  doc["type"] = "position";
  doc["action"] = "set_origin";
  doc["axes"] = axes;
  if (!sendJson(doc)) {
    setLabelText(lblHint, "Origin command not sent");
  } else {
    setLabelText(lblHint, String("Set origin ") + axes + " sent");
    openPage(UiPage::PositionMenu);
  }
}

String runtimeFeedText() {
  return "Feed " + String(feedOverridePct) + "%";
}

String runtimeSpindleText() {
  return "Spindle " + String(spindleOverridePct) + "%";
}

String runtimePauseText() {
  return programPaused ? "Resume" : "Pause";
}

String runtimeAirText() {
  return airOn ? "Air ON" : "Air OFF";
}

void refreshRuntimeUi() {
  setLabelText(lblRuntimeFeed, runtimeFeedText());
  setLabelText(lblRuntimeSpindle, runtimeSpindleText());
  setLabelText(lblRuntimePause, runtimePauseText());
  setLabelText(lblRuntimeAir, runtimeAirText());
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
    case 3:
      return zAxis ? 500 : 1200;
    default:
      return zAxis ? 800 : 2400;
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
  if (strcmp(reason, "timeout") == 0 || strcmp(reason, "jog off") == 0 || strcmp(reason, "disconnect") == 0) {
    setLabelText(lblHint, "Jog stopped");
  }
}

void startOrRefreshContinuousJog(int32_t delta) {
  if (!jogEnabled || delta == 0 || !wasControllerConnected) {
    return;
  }

  const int32_t direction = delta > 0 ? 1 : -1;
  lastMpgDetentMs = millis();
  pendingStepJogDetents = 0;

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
  }
  refreshJogUi();
#if PENDANT_REAL_JOG_ENABLE
  setLabelText(lblHint, enabled ? "Jog enabled: max 2.000" : "Jog disabled: no motion");
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
}

void setJogStepIndex(long index) {
  if (index < 0 || index >= static_cast<long>(JOG_STEP_COUNT)) {
    setLabelText(lblHint, "Use: step 0, 1, 2, 3, or 4");
    return;
  }

  stopContinuousJog("step change");
  resetMpgBurst();
  jogStepIndex = static_cast<size_t>(index);
  refreshJogUi();
  setLabelText(lblHint, "Step set to " + jogStepText());
}

void cycleJogStep() {
  setJogStepIndex(static_cast<long>((jogStepIndex + 1) % JOG_STEP_COUNT));
}

void adjustJogStep(int32_t direction) {
  if (direction == 0) {
    return;
  }

  long next = static_cast<long>(jogStepIndex) + (direction > 0 ? 1 : -1);
  if (next < 0) {
    next = 0;
  } else if (next >= static_cast<long>(JOG_STEP_COUNT)) {
    next = static_cast<long>(JOG_STEP_COUNT) - 1;
  }

  setJogStepIndex(next);
}

void setJogContinuousMode(bool enabled) {
  if (jogContinuousMode == enabled) {
    refreshJogUi();
    return;
  }

  stopContinuousJog("mode change");
  resetMpgBurst();
  pendingStepJogDetents = 0;
  jogContinuousMode = enabled;
  refreshJogUi();
  setLabelText(lblHint, jogContinuousMode ? "Jog mode: Continuous" : "Jog mode: Step");
}

void toggleJogMode() {
  setJogContinuousMode(!jogContinuousMode);
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
}

void finishTouchCalibration() {
  touchCalibrating = false;

  if ((touchMaxX - touchMinX) < 100 || (touchMaxY - touchMinY) < 100) {
    touchCalibrated = false;
    setLabelText(lblHint, "Touch calibration range too small");
    return;
  }

  touchCalibrated = true;
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

bool inRect(uint16_t x, uint16_t y, uint16_t rx, uint16_t ry, uint16_t rw, uint16_t rh) {
  return x >= rx && x < rx + rw && y >= ry && y < ry + rh;
}

bool backButtonRect(UiPage page, uint16_t& x, uint16_t& y, uint16_t& w, uint16_t& h) {
  w = 145;
  h = 40;
  switch (page) {
    case UiPage::MainMenu:
      x = 85;
      y = 196;
      w = 150;
      h = 32;
      return true;
    case UiPage::PositionMenu:
      x = 165;
      y = 160;
      w = 145;
      return true;
    case UiPage::SetOriginMenu:
      x = 165;
      y = 160;
      w = 145;
      return true;
    case UiPage::AtcMenu:
      x = 165;
      y = 192;
      return true;
    case UiPage::MacroMenu:
      x = 10;
      y = 198;
      w = 300;
      h = 30;
      return true;
    case UiPage::ProbeMenu:
      x = 165;
      y = 104;
      return true;
    case UiPage::ProbeSingle:
      x = 165;
      y = 192;
      return true;
    case UiPage::ProbeBore:
      x = 165;
      y = 104;
      return true;
    case UiPage::ProbeBoss:
      x = 165;
      y = 104;
      return true;
    case UiPage::ProbeEdit:
      x = 165;
      y = 170;
      return true;
    case UiPage::ProbeRunning:
      return false;
    default:
      return false;
  }
}

UiPage shortBackTarget(UiPage page) {
  switch (page) {
    case UiPage::MainMenu:
      return UiPage::Home;
    case UiPage::AtcMenu:
    case UiPage::MacroMenu:
    case UiPage::PositionMenu:
      return UiPage::MainMenu;
    case UiPage::SetOriginMenu:
      return UiPage::PositionMenu;
    case UiPage::ProbeMenu:
    case UiPage::ProbeSingle:
    case UiPage::ProbeBore:
    case UiPage::ProbeBoss:
      return page == UiPage::ProbeMenu ? UiPage::MainMenu : UiPage::ProbeMenu;
    case UiPage::ProbeEdit:
      return editReturnPage;
    default:
      return UiPage::Home;
  }
}

bool isLongBackUseful(UiPage page) {
  return page != UiPage::Home && page != UiPage::MainMenu;
}

void openPage(UiPage page) {
  if ((currentPage == UiPage::Home || currentPage == UiPage::RuntimeHome) && page != UiPage::Home && page != UiPage::RuntimeHome) {
    stopContinuousJog("page change");
    resetMpgBurst();
  }
  editSwipeTracking = false;
  backPressTracking = false;
  backLongPressHandled = false;
  runtimeStopTracking = false;
  runtimeStopSent = false;
  currentPage = page;
  renderPage();
  if (page == UiPage::MacroMenu) {
    requestMacroList();
  }
}

void openProbeEditor(ProbeField field, UiPage returnPage) {
  editField = field;
  editReturnPage = returnPage;
  openPage(UiPage::ProbeEdit);
}

void adjustProbeEditValue(float delta) {
  float& value = probeFieldValue(editField);
  value += delta;
  if (value < 0.1f) {
    value = 0.1f;
  }
  value = roundf(value * 10.0f) / 10.0f;
  setLabelText(lblEditValue, probeFieldLabel(editField) + " " + String(value, 1));
}

bool handleBackButtonHold(uint16_t screenX, uint16_t screenY) {
  uint16_t x = 0;
  uint16_t y = 0;
  uint16_t w = 0;
  uint16_t h = 0;
  if (!backButtonRect(currentPage, x, y, w, h) || !inRect(screenX, screenY, x, y, w, h)) {
    backPressTracking = false;
    return false;
  }

  const uint32_t now = millis();
  if (!backPressTracking || backPressPage != currentPage) {
    backPressTracking = true;
    backLongPressHandled = false;
    backPressStartMs = now;
    backPressPage = currentPage;
    return true;
  }

  if (!backLongPressHandled && isLongBackUseful(backPressPage) && now - backPressStartMs >= BACK_LONG_PRESS_MS) {
    backLongPressHandled = true;
    touchCapturedUntilRelease = true;
    openPage(UiPage::Home);
    return true;
  }

  return true;
}

void releaseBackButtonHold() {
  if (!backPressTracking) {
    return;
  }

  const UiPage page = backPressPage;
  const bool longHandled = backLongPressHandled;
  backPressTracking = false;
  backLongPressHandled = false;

  if (!longHandled) {
    openPage(shortBackTarget(page));
  }
}

bool handleRuntimeStopHold(uint16_t screenX, uint16_t screenY) {
  if (currentPage != UiPage::RuntimeHome || !inRect(screenX, screenY, 10, 160, 145, 46)) {
    runtimeStopTracking = false;
    runtimeStopSent = false;
    return false;
  }

  const uint32_t now = millis();
  if (!runtimeStopTracking) {
    runtimeStopTracking = true;
    runtimeStopSent = false;
    runtimeStopStartMs = now;
    setLabelText(lblHint, "Hold to stop");
    return true;
  }

  if (!runtimeStopSent && now - runtimeStopStartMs >= BACK_LONG_PRESS_MS) {
    runtimeStopSent = true;
    touchCapturedUntilRelease = true;
    sendRuntimeCommand("stop");
    setLabelText(lblHint, "Stop sent");
    return true;
  }

  return true;
}

void releaseRuntimeStopHold() {
  runtimeStopTracking = false;
  runtimeStopSent = false;
}

bool handleProbeEditSwipe(uint16_t screenX, uint16_t screenY) {
  if (currentPage != UiPage::ProbeEdit) {
    editSwipeTracking = false;
    return false;
  }

  if (!inRect(screenX, screenY, 70, 48, 180, 42)) {
    editSwipeTracking = false;
    return false;
  }

  if (!editSwipeTracking) {
    editSwipeTracking = true;
    editSwipeStartX = screenX;
    editSwipeLastX = screenX;
    return true;
  }

  const int16_t delta = static_cast<int16_t>(screenX) - static_cast<int16_t>(editSwipeLastX);
  if (delta >= 24) {
    adjustProbeEditValue(1.0f);
    editSwipeLastX = screenX;
    return true;
  }
  if (delta <= -24) {
    adjustProbeEditValue(-1.0f);
    editSwipeLastX = screenX;
    return true;
  }

  if (abs(static_cast<int16_t>(screenX) - static_cast<int16_t>(editSwipeStartX)) > 8) {
    return true;
  }
  return false;
}

bool handleTouchButton(uint16_t screenX, uint16_t screenY) {
  const uint32_t now = millis();
  if (now - lastTouchButtonMs < TOUCH_BUTTON_DEBOUNCE_MS) {
    return true;
  }
  lastTouchButtonMs = now;

  if (currentPage == UiPage::RuntimeHome) {
    if (inRect(screenX, screenY, 10, 48, 145, 54)) {
      runtimeTarget = RuntimeTarget::Feed;
      renderPage();
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 54)) {
      runtimeTarget = RuntimeTarget::Spindle;
      renderPage();
      return true;
    }
    if (inRect(screenX, screenY, 10, 112, 145, 40)) {
      sendRuntimeCommand("pause_resume");
      return true;
    }
    if (inRect(screenX, screenY, 165, 112, 145, 40)) {
      sendRuntimeAirToggle();
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeRunning) {
    if (inRect(screenX, screenY, 85, 122, 150, 54)) {
      sendProbeCancelCommand();
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::MainMenu) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      openPage(UiPage::ProbeMenu);
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 40)) {
      openPage(UiPage::AtcMenu);
      return true;
    }
    if (inRect(screenX, screenY, 10, 104, 145, 40)) {
      openPage(UiPage::MacroMenu);
      return true;
    }
    if (inRect(screenX, screenY, 165, 104, 145, 40)) {
      openPage(UiPage::PositionMenu);
      return true;
    }
    if (inRect(screenX, screenY, 85, 196, 150, 32)) {
      openPage(UiPage::Home);
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::PositionMenu) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      sendPositionGotoCommand("work_origin");
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 40)) {
      sendPositionGotoCommand("path_origin");
      return true;
    }
    if (inRect(screenX, screenY, 10, 104, 145, 40)) {
      openPage(UiPage::SetOriginMenu);
      return true;
    }
    if (inRect(screenX, screenY, 165, 160, 145, 40)) {
      openPage(UiPage::MainMenu);
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::SetOriginMenu) {
    if (inRect(screenX, screenY, 10, 96, 145, 48)) {
      sendSetOriginCommand("xy");
      return true;
    }
    if (inRect(screenX, screenY, 165, 96, 145, 48)) {
      sendSetOriginCommand("xyz");
      return true;
    }
    if (inRect(screenX, screenY, 165, 160, 145, 40)) {
      openPage(UiPage::PositionMenu);
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::MacroMenu) {
    const uint8_t visibleMacros = min(macroCount, MAX_VISIBLE_MACROS);
    for (uint8_t i = 0; i < visibleMacros; ++i) {
      const uint8_t col = i % 2;
      const uint8_t row = i / 2;
      const uint16_t x = col == 0 ? 10 : 165;
      const uint16_t y = 38 + row * 40;
      if (inRect(screenX, screenY, x, y, 145, 38)) {
        sendMacroRunCommand(i);
        return true;
      }
    }
    return false;
  }

  if (currentPage == UiPage::AtcMenu) {
    if (inRect(screenX, screenY, 10, 40, 93, 32)) {
      sendToolChangeCommand(1);
      return true;
    }
    if (inRect(screenX, screenY, 113, 40, 94, 32)) {
      sendToolChangeCommand(2);
      return true;
    }
    if (inRect(screenX, screenY, 217, 40, 93, 32)) {
      sendToolChangeCommand(3);
      return true;
    }
    if (inRect(screenX, screenY, 10, 78, 93, 32)) {
      sendToolChangeCommand(4);
      return true;
    }
    if (inRect(screenX, screenY, 113, 78, 94, 32)) {
      sendToolChangeCommand(5);
      return true;
    }
    if (inRect(screenX, screenY, 217, 78, 93, 32)) {
      sendToolChangeCommand(6);
      return true;
    }
    if (inRect(screenX, screenY, 10, 116, 145, 32)) {
      sendToolChangeCommand(0);
      return true;
    }
    if (inRect(screenX, screenY, 165, 116, 145, 32)) {
      sendToolChangeCommand(999990);
      return true;
    }
    if (inRect(screenX, screenY, 10, 154, 93, 32)) {
      sendToolDropCommand();
      return true;
    }
    if (inRect(screenX, screenY, 113, 154, 94, 32)) {
      sendToolClampCommand(true);
      return true;
    }
    if (inRect(screenX, screenY, 217, 154, 93, 32)) {
      sendToolClampCommand(false);
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeMenu) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      openPage(UiPage::ProbeSingle);
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 40)) {
      openPage(UiPage::ProbeBore);
      return true;
    }
    if (inRect(screenX, screenY, 10, 104, 145, 40)) {
      openPage(UiPage::ProbeBoss);
      return true;
    }
    if (inRect(screenX, screenY, 165, 104, 145, 40)) {
      openPage(UiPage::MainMenu);
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeSingle) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      openProbeEditor(ProbeField::SingleDistance, UiPage::ProbeSingle);
      return true;
    }
    if (inRect(screenX, screenY, 10, 96, 145, 40)) {
      sendGcodeCommand("M466 X-" + String(singleProbeDistance, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 165, 96, 145, 40)) {
      sendGcodeCommand("M466 X" + String(singleProbeDistance, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 10, 144, 145, 40)) {
      sendGcodeCommand("M466 Y" + String(singleProbeDistance, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 165, 144, 145, 40)) {
      sendGcodeCommand("M466 Y-" + String(singleProbeDistance, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 10, 192, 145, 40)) {
      sendGcodeCommand("M466 Z-" + String(singleProbeDistance, 1) + " S2");
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeBore) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      openProbeEditor(ProbeField::BoreX, UiPage::ProbeBore);
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 40)) {
      openProbeEditor(ProbeField::BoreY, UiPage::ProbeBore);
      return true;
    }
    if (inRect(screenX, screenY, 165, 104, 145, 40)) {
      openPage(UiPage::ProbeMenu);
      return true;
    }
    if (inRect(screenX, screenY, 10, 160, 93, 40)) {
      sendGcodeCommand("M461 X" + String(boreProbeX, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 113, 160, 94, 40)) {
      sendGcodeCommand("M461 Y" + String(boreProbeY, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 217, 160, 93, 40)) {
      sendGcodeCommand("M461 X" + String(boreProbeX, 1) + " Y" + String(boreProbeY, 1) + " S1");
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeBoss) {
    if (inRect(screenX, screenY, 10, 48, 145, 40)) {
      openProbeEditor(ProbeField::BossX, UiPage::ProbeBoss);
      return true;
    }
    if (inRect(screenX, screenY, 165, 48, 145, 40)) {
      openProbeEditor(ProbeField::BossY, UiPage::ProbeBoss);
      return true;
    }
    if (inRect(screenX, screenY, 10, 104, 145, 40)) {
      openProbeEditor(ProbeField::BossDepth, UiPage::ProbeBoss);
      return true;
    }
    if (inRect(screenX, screenY, 165, 104, 145, 40)) {
      openPage(UiPage::ProbeMenu);
      return true;
    }
    if (inRect(screenX, screenY, 10, 160, 93, 40)) {
      sendGcodeCommand("M462 X" + String(bossProbeX, 1) + " E" + String(bossProbeDepth, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 113, 160, 94, 40)) {
      sendGcodeCommand("M462 Y" + String(bossProbeY, 1) + " E" + String(bossProbeDepth, 1) + " S1");
      return true;
    }
    if (inRect(screenX, screenY, 217, 160, 93, 40)) {
      sendGcodeCommand("M462 X" + String(bossProbeX, 1) + " Y" + String(bossProbeY, 1) + " E" + String(bossProbeDepth, 1) + " S1");
      return true;
    }
    return false;
  }

  if (currentPage == UiPage::ProbeEdit) {
    if (inRect(screenX, screenY, 10, 106, 70, 40)) {
      adjustProbeEditValue(-1.0f);
      return true;
    }
    if (inRect(screenX, screenY, 88, 106, 70, 40)) {
      adjustProbeEditValue(-0.1f);
      return true;
    }
    if (inRect(screenX, screenY, 166, 106, 70, 40)) {
      adjustProbeEditValue(0.1f);
      return true;
    }
    if (inRect(screenX, screenY, 244, 106, 66, 40)) {
      adjustProbeEditValue(1.0f);
      return true;
    }
    if (inRect(screenX, screenY, 10, 170, 145, 40)) {
      saveProbeField(editField);
      openPage(editReturnPage);
      return true;
    }
    if (inRect(screenX, screenY, 165, 170, 145, 40)) {
      openPage(editReturnPage);
      return true;
    }
    return false;
  }

  if (currentPage != UiPage::Home) {
    return false;
  }

  if (screenX >= AXIS_TILE_X && screenX < AXIS_TILE_X + AXIS_TILE_W) {
    const uint16_t axisY = AXIS_TILE_Y;
    if (screenY >= axisY && screenY < axisY + AXIS_TILE_H) {
      setJogAxis('X');
      return true;
    }

    const uint16_t yTileY = axisY + AXIS_TILE_H + AXIS_TILE_GAP;
    if (screenY >= yTileY && screenY < yTileY + AXIS_TILE_H) {
      setJogAxis('Y');
      return true;
    }

    const uint16_t zTileY = yTileY + AXIS_TILE_H + AXIS_TILE_GAP;
    if (screenY >= zTileY && screenY < zTileY + AXIS_TILE_H) {
      setJogAxis('Z');
      return true;
    }
  }

  if (screenY < BOTTOM_BUTTON_Y || screenY >= BOTTOM_BUTTON_Y + BOTTOM_BUTTON_H) {
    if (inRect(screenX, screenY, 225, 48, 85, 40)) {
      openPage(UiPage::MainMenu);
      return true;
    }
    const uint16_t coordX = BOTTOM_BUTTON_FIRST_X + (BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP) * 2;
    const uint16_t coordY = BOTTOM_BUTTON_Y - BOTTOM_BUTTON_H - 8;
    if (inRect(screenX, screenY, coordX, coordY, BOTTOM_BUTTON_W, BOTTOM_BUTTON_H)) {
      toggleCoordinateDisplay();
      return true;
    }
    return false;
  }

  if (!wasControllerConnected) {
    setLabelText(lblHint, "Controller disconnected");
    return true;
  }

  if (screenX >= BOTTOM_BUTTON_FIRST_X && screenX < BOTTOM_BUTTON_FIRST_X + BOTTOM_BUTTON_W) {
    setJogEnabled(!jogEnabled);
    return true;
  }

  const uint16_t stepX = BOTTOM_BUTTON_FIRST_X + BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP;
  if (screenX >= stepX && screenX < stepX + BOTTOM_BUTTON_W) {
    cycleJogStep();
    return true;
  }

  const uint16_t modeX = stepX + BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP;
  if (screenX >= modeX && screenX < modeX + BOTTOM_BUTTON_W) {
    toggleJogMode();
    return true;
  }

  return false;
}

void updateConnectionUi(bool connected) {
  if (connected) {
    refreshTopBar();
    refreshJogUi();
    setLabelText(lblHint, "Ready");
  } else {
    stopContinuousJog("disconnect");
    controllerJogAllowed = false;
    jogEnabled = false;
    programRunning = false;
    programPaused = false;
    controllerState = "disconnected";
    controllerActivity = "disconnected";
    refreshTopBar();
    refreshJogUi();
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
  lv_obj_set_size(button, BOTTOM_BUTTON_W, BOTTOM_BUTTON_H);
  lv_obj_align(button, LV_ALIGN_TOP_LEFT, x, BOTTOM_BUTTON_Y);
  lv_obj_clear_flag(button, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scrollbar_mode(button, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_bg_color(button, lv_color_hex(0x1E5A7A), 0);
  lv_obj_set_style_bg_opa(button, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(button, lv_color_hex(0x68BCE0), 0);
  lv_obj_set_style_border_width(button, 1, 0);
  lv_obj_set_style_radius(button, 6, 0);

  lv_obj_t* label = lv_label_create(button);
  styleLabel(label);
  lv_obj_set_width(label, BOTTOM_BUTTON_W - 8);
  lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
  lv_label_set_text(label, text);
  lv_obj_center(label);
  return label;
}

lv_color_t buttonBgColor(ButtonStyle style, bool enabled) {
  if (!enabled) {
    return lv_color_hex(0x333333);
  }
  switch (style) {
    case ButtonStyle::Back:
      return lv_color_hex(0x8A6A00);
    case ButtonStyle::Save:
      return lv_color_hex(0x1F7A3A);
    case ButtonStyle::RuntimeNormal:
      return lv_color_hex(0xE6EAF0);
    case ButtonStyle::RuntimeSelected:
      return lv_color_hex(0x0066AA);
    case ButtonStyle::Warning:
      return lv_color_hex(0xB87800);
    case ButtonStyle::Danger:
      return lv_color_hex(0xB3261E);
    case ButtonStyle::AirOn:
      return lv_color_hex(0x1F7A3A);
    case ButtonStyle::CoordWork:
      return lv_color_hex(0x255D4A);
    case ButtonStyle::Normal:
    default:
      return lv_color_hex(0x1E5A7A);
  }
}

lv_color_t buttonBorderColor(ButtonStyle style, bool enabled) {
  if (!enabled) {
    return lv_color_hex(0x666666);
  }
  switch (style) {
    case ButtonStyle::Back:
      return lv_color_hex(0xFFD34D);
    case ButtonStyle::Save:
      return lv_color_hex(0x67D98D);
    case ButtonStyle::RuntimeNormal:
      return lv_color_hex(0xB8C2CF);
    case ButtonStyle::RuntimeSelected:
      return lv_color_hex(0x68BCE0);
    case ButtonStyle::Warning:
      return lv_color_hex(0xFFD34D);
    case ButtonStyle::Danger:
      return lv_color_hex(0xFF8A80);
    case ButtonStyle::AirOn:
      return lv_color_hex(0x67D98D);
    case ButtonStyle::CoordWork:
      return lv_color_hex(0x6FAF9B);
    case ButtonStyle::Normal:
    default:
      return lv_color_hex(0x68BCE0);
  }
}

lv_color_t buttonTextColor(ButtonStyle style, bool enabled) {
  if (!enabled) {
    return lv_color_hex(0x999999);
  }
  if (style == ButtonStyle::RuntimeNormal) {
    return lv_color_hex(0x17212B);
  }
  return lv_color_white();
}

lv_obj_t* createButton(uint16_t x, uint16_t y, uint16_t w, uint16_t h, const char* text, bool enabled = true, ButtonStyle buttonStyle = ButtonStyle::Normal) {
  lv_obj_t* button = lv_obj_create(lv_scr_act());
  lv_obj_set_size(button, w, h);
  lv_obj_align(button, LV_ALIGN_TOP_LEFT, x, y);
  lv_obj_clear_flag(button, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scrollbar_mode(button, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_bg_color(button, buttonBgColor(buttonStyle, enabled), 0);
  lv_obj_set_style_bg_opa(button, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(button, buttonBorderColor(buttonStyle, enabled), 0);
  lv_obj_set_style_border_width(button, 1, 0);
  lv_obj_set_style_radius(button, 6, 0);

  lv_obj_t* label = lv_label_create(button);
  styleLabel(label);
  lv_obj_set_width(label, w - 8);
  lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_color(label, buttonTextColor(buttonStyle, enabled), 0);
  lv_label_set_text(label, text);
  lv_obj_center(label);
  return label;
}

lv_obj_t* createAxisTile(uint16_t y, char axis) {
  lv_obj_t* tile = lv_obj_create(lv_scr_act());
  lv_obj_set_size(tile, AXIS_TILE_W, AXIS_TILE_H);
  lv_obj_align(tile, LV_ALIGN_TOP_LEFT, AXIS_TILE_X, y);
  lv_obj_clear_flag(tile, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scrollbar_mode(tile, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(tile, 6, 0);

  lv_obj_t* label = lv_label_create(tile);
  lv_obj_set_style_text_font(label, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0);
  lv_obj_set_width(label, AXIS_TILE_W - 16);
  lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
  char text[2] = {axis, '\0'};
  lv_label_set_text(label, text);
  lv_obj_center(label);
  return label;
}

void createHeader() {
  headerBar = lv_obj_create(lv_scr_act());
  lv_obj_set_size(headerBar, SCREEN_WIDTH, 32);
  lv_obj_align(headerBar, LV_ALIGN_TOP_LEFT, 0, 0);
  lv_obj_set_style_bg_color(headerBar, lv_color_hex(0x0066AA), 0);
  lv_obj_set_style_bg_opa(headerBar, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(headerBar, 0, 0);
  lv_obj_set_style_radius(headerBar, 0, 0);

  lblStatus = lv_label_create(lv_scr_act());
  styleLabel(lblStatus);
  lv_obj_align(lblStatus, LV_ALIGN_TOP_LEFT, 10, 6);
  lv_label_set_long_mode(lblStatus, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(lblStatus, 300);
}

void renderHomePage() {
  lblAxisX = createAxisTile(AXIS_TILE_Y, 'X');
  lblAxisY = createAxisTile(AXIS_TILE_Y + AXIS_TILE_H + AXIS_TILE_GAP, 'Y');
  lblAxisZ = createAxisTile(AXIS_TILE_Y + (AXIS_TILE_H + AXIS_TILE_GAP) * 2, 'Z');
  lblMenuButton = createButton(225, 48, 85, 40, "Menu");

  lblJogButton = createBottomButton(BOTTOM_BUTTON_FIRST_X, "Jog OFF");
  lblStepButton = createBottomButton(BOTTOM_BUTTON_FIRST_X + (BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP), "0.010");
  lblModeButton = createBottomButton(BOTTOM_BUTTON_FIRST_X + (BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP) * 2, "Step");
  lblCoordButton = createButton(
      BOTTOM_BUTTON_FIRST_X + (BOTTOM_BUTTON_W + BOTTOM_BUTTON_GAP) * 2,
      BOTTOM_BUTTON_Y - BOTTOM_BUTTON_H - 8,
      BOTTOM_BUTTON_W,
      BOTTOM_BUTTON_H,
      showWorkCoordinates ? "WORK" : "MACHINE",
      true,
      showWorkCoordinates ? ButtonStyle::CoordWork : ButtonStyle::Normal);

  refreshPositionLabel();
  refreshJogUi();
  refreshCoordinateButton();
}

void renderRuntimeHomePage() {
  const ButtonStyle feedStyle = runtimeTarget == RuntimeTarget::Feed ? ButtonStyle::RuntimeSelected : ButtonStyle::RuntimeNormal;
  const ButtonStyle spindleStyle = runtimeTarget == RuntimeTarget::Spindle ? ButtonStyle::RuntimeSelected : ButtonStyle::RuntimeNormal;

  lblRuntimeFeed = createButton(10, 48, 145, 54, runtimeFeedText().c_str(), true, feedStyle);
  lblRuntimeSpindle = createButton(165, 48, 145, 54, runtimeSpindleText().c_str(), true, spindleStyle);
  lblRuntimePause = createButton(10, 112, 145, 40, runtimePauseText().c_str(), true, programPaused ? ButtonStyle::Save : ButtonStyle::Warning);
  lblRuntimeAir = createButton(165, 112, 145, 40, runtimeAirText().c_str(), true, airOn ? ButtonStyle::AirOn : ButtonStyle::RuntimeNormal);
  createButton(10, 160, 145, 46, "Stop", true, ButtonStyle::Danger);

  lv_obj_t* note = lv_label_create(lv_scr_act());
  lv_obj_set_style_text_font(note, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(note, lv_color_hex(0x17212B), 0);
  lv_obj_align(note, LV_ALIGN_TOP_LEFT, 165, 170);
  lv_obj_set_width(note, 145);
  lv_label_set_long_mode(note, LV_LABEL_LONG_WRAP);
  lv_label_set_text(note, "Hold Stop");
}

void renderMainMenuPage() {
  createButton(10, 48, 145, 40, "Probing");
  createButton(165, 48, 145, 40, "ATC");
  createButton(10, 104, 145, 40, "Macros");
  createButton(165, 104, 145, 40, "Position");
  createButton(85, 196, 150, 32, "Back", true, ButtonStyle::Back);
}

void renderPositionMenuPage() {
  createButton(10, 48, 145, 40, LV_SYMBOL_RIGHT " Work Origin");
  createButton(165, 48, 145, 40, LV_SYMBOL_RIGHT " Path Origin");
  createButton(10, 104, 145, 40, "Set Origin Here", true, ButtonStyle::Warning);
  createButton(165, 160, 145, 40, "Back", true, ButtonStyle::Back);
}

void renderSetOriginMenuPage() {
  lv_obj_t* title = lv_label_create(lv_scr_act());
  lv_obj_set_width(title, 300);
  lv_obj_set_style_text_font(title, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(title, lv_color_white(), 0);
  lv_label_set_long_mode(title, LV_LABEL_LONG_WRAP);
  lv_label_set_text(title, "Set origin from current position");
  lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 48);

  lv_obj_t* prompt = lv_label_create(lv_scr_act());
  lv_obj_set_style_text_font(prompt, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(prompt, lv_color_hex(0xB7C3CC), 0);
  lv_label_set_text(prompt, "Choose axes");
  lv_obj_align(prompt, LV_ALIGN_TOP_MID, 0, 72);

  createButton(10, 96, 145, 48, "X/Y", true, ButtonStyle::Warning);
  createButton(165, 96, 145, 48, "X/Y/Z", true, ButtonStyle::Danger);
  createButton(165, 160, 145, 40, "Back", true, ButtonStyle::Back);
}

void renderAtcMenuPage() {
  createButton(10, 40, 93, 32, "T1");
  createButton(113, 40, 94, 32, "T2");
  createButton(217, 40, 93, 32, "T3");
  createButton(10, 78, 93, 32, "T4");
  createButton(113, 78, 94, 32, "T5");
  createButton(217, 78, 93, 32, "T6");
  createButton(10, 116, 145, 32, "Probe");
  createButton(165, 116, 145, 32, "3D Probe");
  createButton(10, 154, 93, 32, "Drop");
  createButton(113, 154, 94, 32, "Clamp", true, ButtonStyle::Save);
  createButton(217, 154, 93, 32, "Unclamp", true, ButtonStyle::Warning);
  createButton(165, 192, 145, 32, "Back", true, ButtonStyle::Back);
}

void renderMacroMenuPage() {
  if (macroCount == 0) {
    createButton(45, 84, 230, 44, "No named macros", false);
  } else {
    const uint8_t visibleMacros = min(macroCount, MAX_VISIBLE_MACROS);
    for (uint8_t i = 0; i < visibleMacros; ++i) {
      const uint8_t col = i % 2;
      const uint8_t row = i / 2;
      const uint16_t x = col == 0 ? 10 : 165;
      const uint16_t y = 38 + row * 40;
      createButton(x, y, 145, 38, macroNames[i].c_str());
    }
    if (macroCount > MAX_VISIBLE_MACROS) {
      createButton(10, 198, 145, 30, "More later", false);
      createButton(165, 198, 145, 30, "Back", true, ButtonStyle::Back);
      return;
    }
  }
  createButton(10, 198, 300, 30, "Back", true, ButtonStyle::Back);
}

void renderProbeMenuPage() {
  createButton(10, 48, 145, 40, "Single Axis");
  createButton(165, 48, 145, 40, "Bore");
  createButton(10, 104, 145, 40, "Boss");
  createButton(165, 104, 145, 40, "Back", true, ButtonStyle::Back);
}

void renderSingleProbePage() {
  lblProbeValue1 = createButton(10, 48, 145, 40, probeValueText("Dist", singleProbeDistance).c_str());
  createButton(10, 96, 145, 40, "X Left");
  createButton(165, 96, 145, 40, "X Right");
  createButton(10, 144, 145, 40, "Y Forward");
  createButton(165, 144, 145, 40, "Y Back");
  createButton(10, 192, 145, 40, "Z Down");
  createButton(165, 192, 145, 40, "Back", true, ButtonStyle::Back);
}

void renderBoreProbePage() {
  lblProbeValue1 = createButton(10, 48, 145, 40, probeValueText("X", boreProbeX).c_str());
  lblProbeValue2 = createButton(165, 48, 145, 40, probeValueText("Y", boreProbeY).c_str());
  createButton(165, 104, 145, 40, "Back", true, ButtonStyle::Back);
  createButton(10, 160, 93, 40, "Probe X");
  createButton(113, 160, 94, 40, "Probe Y");
  createButton(217, 160, 93, 40, "Probe X/Y");
}

void renderBossProbePage() {
  lblProbeValue1 = createButton(10, 48, 145, 40, probeValueText("X", bossProbeX).c_str());
  lblProbeValue2 = createButton(165, 48, 145, 40, probeValueText("Y", bossProbeY).c_str());
  lblProbeValue3 = createButton(10, 104, 145, 40, probeValueText("Depth", bossProbeDepth).c_str());
  createButton(165, 104, 145, 40, "Back", true, ButtonStyle::Back);
  createButton(10, 160, 93, 40, "Probe X");
  createButton(113, 160, 94, 40, "Probe Y");
  createButton(217, 160, 93, 40, "Probe X/Y");
}

void renderEditProbePage() {
  String valueText = probeFieldLabel(editField) + " " + String(probeFieldValue(editField), 1);
  lblEditValue = createButton(70, 48, 180, 42, valueText.c_str());
  createButton(10, 106, 70, 40, "-1");
  createButton(88, 106, 70, 40, "-0.1");
  createButton(166, 106, 70, 40, "+0.1");
  createButton(244, 106, 66, 40, "+1");
  createButton(10, 170, 145, 40, "Save", true, ButtonStyle::Save);
  createButton(165, 170, 145, 40, "Back", true, ButtonStyle::Back);
}

void renderProbeRunningPage() {
  lv_obj_t* title = lv_label_create(lv_scr_act());
  lv_obj_set_style_text_font(title, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(title, lv_color_hex(0x17212B), 0);
  lv_label_set_text(title, "PROBING");
  lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 54);

  lv_obj_t* body = lv_label_create(lv_scr_act());
  lv_obj_set_style_text_font(body, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(body, lv_color_hex(0x394552), 0);
  lv_label_set_text(body, probeMotionSeen ? "Running..." : "Starting...");
  lv_obj_align(body, LV_ALIGN_TOP_MID, 0, 86);

  createButton(85, 122, 150, 54, "Cancel", true, ButtonStyle::Danger);
}

void renderPage() {
  lv_obj_clean(lv_scr_act());
  headerBar = nullptr;
  lblStatus = nullptr;
  lblHint = nullptr;
  lblJogButton = nullptr;
  lblStepButton = nullptr;
  lblModeButton = nullptr;
  lblCoordButton = nullptr;
  lblAxisX = nullptr;
  lblAxisY = nullptr;
  lblAxisZ = nullptr;
  lblMenuButton = nullptr;
  lblProbeValue1 = nullptr;
  lblProbeValue2 = nullptr;
  lblProbeValue3 = nullptr;
  lblEditValue = nullptr;
  lblRuntimeFeed = nullptr;
  lblRuntimeSpindle = nullptr;
  lblRuntimePause = nullptr;
  lblRuntimeAir = nullptr;

  const bool lightPage = currentPage == UiPage::RuntimeHome || currentPage == UiPage::ProbeRunning;
  lv_obj_set_style_bg_color(lv_scr_act(), lightPage ? lv_color_hex(0xF7F7F2) : lv_color_hex(0x101820), 0);
  lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);
  createHeader();

  switch (currentPage) {
    case UiPage::Home:
      renderHomePage();
      break;
    case UiPage::RuntimeHome:
      renderRuntimeHomePage();
      break;
    case UiPage::MainMenu:
      renderMainMenuPage();
      break;
    case UiPage::PositionMenu:
      renderPositionMenuPage();
      break;
    case UiPage::SetOriginMenu:
      renderSetOriginMenuPage();
      break;
    case UiPage::AtcMenu:
      renderAtcMenuPage();
      break;
    case UiPage::MacroMenu:
      renderMacroMenuPage();
      break;
    case UiPage::ProbeMenu:
      renderProbeMenuPage();
      break;
    case UiPage::ProbeSingle:
      renderSingleProbePage();
      break;
    case UiPage::ProbeBore:
      renderBoreProbePage();
      break;
    case UiPage::ProbeBoss:
      renderBossProbePage();
      break;
    case UiPage::ProbeEdit:
      renderEditProbePage();
      break;
    case UiPage::ProbeRunning:
      renderProbeRunningPage();
      break;
  }

  refreshTopBar();
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
  StaticJsonDocument<2048> doc;
  const DeserializationError err = deserializeJson(doc, line);
  if (err) {
    return;
  }

  const String type = String(doc["type"] | "");
  if (type == "pos") {
    mx = doc["mx"] | mx;
    my = doc["my"] | my;
    mz = doc["mz"] | mz;
    if (!doc.containsKey("mx")) {
      mx = doc["x"] | mx;
      my = doc["y"] | my;
      mz = doc["z"] | mz;
    }
    wx = doc["wx"] | wx;
    wy = doc["wy"] | wy;
    wz = doc["wz"] | wz;
    refreshPositionLabel();
    return;
  }

  if (type == "machine_state") {
    const bool wasRuntimeActive = runtimeActive();
    controllerState = String(doc["state"] | "unknown");
    controllerActivity = String(doc["activity"] | "unknown");
    toolLabel = String(doc["tool_label"] | "");
    targetToolLabel = String(doc["target_tool_label"] | "");
    programRunning = doc["program_running"] | false;
    programPaused = doc["program_paused"] | false;
    feedOverridePct = doc["feed_override"] | feedOverridePct;
    spindleOverridePct = doc["spindle_override"] | spindleOverridePct;
    airOn = doc["air_on"] | airOn;
    playedPercent = doc["playedpercent"] | playedPercent;
    if (toolLabel.length() == 0) {
      toolLabel = localToolLabel(doc["tool"] | -1);
    }
    if (targetToolLabel.length() == 0) {
      targetToolLabel = localToolLabel(doc["target_tool"] | -1);
    }
    const bool nextJogAllowed = doc["jog_allowed"] | false;
    if (controllerJogAllowed != nextJogAllowed) {
      controllerJogAllowed = nextJogAllowed;
      refreshJogUi();
    }

    String stateLower = controllerState;
    stateLower.toLowerCase();
    const bool controllerIdle = stateLower == "idle" || stateLower.length() == 0;
    if (currentPage == UiPage::ProbeRunning) {
      if (!controllerIdle && !probeMotionSeen) {
        probeMotionSeen = true;
        renderPage();
        return;
      }
      if (probeCommandActive && probeMotionSeen && controllerIdle) {
        probeCommandActive = false;
        probeMotionSeen = false;
        openPage(probeReturnPage);
        return;
      }
      refreshTopBar();
      return;
    }

    if (runtimeActive() && currentPage != UiPage::RuntimeHome) {
      openPage(UiPage::RuntimeHome);
      return;
    }
    if (!runtimeActive() && wasRuntimeActive && currentPage == UiPage::RuntimeHome) {
      openPage(UiPage::Home);
      return;
    }

    refreshTopBar();
    refreshRuntimeUi();
    return;
  }

  if (type == "jog_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    if (!ok) {
      setLabelText(lblHint, "Jog rejected: " + reason);
    }
    return;
  }

  if (type == "gcode_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    if (!ok) {
      probeCommandActive = false;
      probeMotionSeen = false;
      if (currentPage == UiPage::ProbeRunning) {
        openPage(probeReturnPage);
      }
      setLabelText(lblHint, "Probe rejected: " + reason);
    } else {
      setLabelText(lblHint, "Probe running...");
    }
    return;
  }

  if (type == "tool_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    if (!ok) {
      setLabelText(lblStatus, "Tool rejected");
      setLabelText(lblHint, "Tool rejected: " + reason);
    } else {
      setLabelText(lblStatus, "Tool command sent");
      setLabelText(lblHint, "Tool command sent");
    }
    return;
  }

  if (type == "macro_list") {
    macroCount = 0;
    JsonArray macros = doc["macros"].as<JsonArray>();
    for (JsonObject macro : macros) {
      if (macroCount >= MAX_MACROS) {
        break;
      }
      const int id = macro["id"] | 0;
      const String name = String(macro["name"] | "");
      if (id <= 0 || name.length() == 0) {
        continue;
      }
      macroIds[macroCount] = id;
      macroNames[macroCount] = name;
      ++macroCount;
    }
    if (currentPage == UiPage::MacroMenu) {
      renderPage();
    }
    return;
  }

  if (type == "macro_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    setLabelText(lblHint, ok ? "Macro sent" : "Macro rejected: " + reason);
    return;
  }

  if (type == "runtime_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    const String action = String(doc["action"] | "");
    if (action == "probe_cancel") {
      setLabelText(lblHint, ok ? "Cancel sent" : "Cancel rejected: " + reason);
    } else {
      setLabelText(lblHint, ok ? "Runtime command sent" : "Runtime rejected: " + reason);
    }
    return;
  }

  if (type == "position_result") {
    const bool ok = doc["ok"] | false;
    const String reason = String(doc["reason"] | "");
    const String message = String(doc["message"] | "");
    if (ok) {
      setLabelText(lblHint, message.length() > 0 ? message : "Position command sent");
    } else {
      setLabelText(lblHint, "Position rejected: " + reason);
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

  if (!touched) {
    touchCapturedUntilRelease = false;
    releaseBackButtonHold();
    releaseRuntimeStopHold();
    editSwipeTracking = false;
    return;
  }

  if (touchCapturedUntilRelease) {
    return;
  }

  if (now - lastTouchReportMs < 150) {
    return;
  }

  lastTouchReportMs = now;

  if (touchCalibrating) {
    updateTouchCalibration(rawX, rawY);
    setLabelText(lblHint, "Cal raw x:" + String(rawX) + " y:" + String(rawY));
    return;
  }

  if (touchCalibrated) {
    uint16_t screenX = 0;
    uint16_t screenY = 0;
    mapTouchToScreen(rawX, rawY, screenX, screenY);
    if (handleBackButtonHold(screenX, screenY)) {
      return;
    }
    if (handleRuntimeStopHold(screenX, screenY)) {
      return;
    }
    if (handleProbeEditSwipe(screenX, screenY)) {
      return;
    }
    const bool handledByButton = handleTouchButton(screenX, screenY);
    if (handledByButton) {
      return;
    }
    return;
  }

#endif
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  setLabelText(lblStatus, "Connecting to WiFi...");
  uint32_t startMs = millis();
  while (WiFi.status() != WL_CONNECTED) {
    lv_tick_inc(250);
    lv_timer_handler();
    delay(250);
    if (millis() - startMs > 30000) {
      startMs = millis();
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
#endif
}

void handleMpgEvent(int32_t position, int32_t delta) {
  (void)position;
  if (currentPage != UiPage::Home) {
    return;
  }

  refreshJogUi();

  if (!jogEnabled || delta == 0) {
    return;
  }

  if (jogContinuousMode) {
    startOrRefreshContinuousJog(delta);
    return;
  }

  queueStepJogDelta(delta);
  servicePendingStepJog(false);
}

void handleMpgStartEvent(int32_t direction) {
  if (currentPage != UiPage::Home) {
    return;
  }

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

  if (jogEnabled && jogContinuousMode) {
    startOrRefreshContinuousJog(normalizedDirection);
  }
}

void handleMpgStopEvent() {
  stopContinuousJog("mpg stop");
  resetMpgBurst();
}

bool handleRpEvent(const String& line) {
  long position = 0;
  long delta = 0;
  long direction = 0;

  if (sscanf(line.c_str(), "ENC_TICK %ld", &delta) == 1) {
    if (currentPage == UiPage::ProbeEdit) {
      adjustProbeEditValue(static_cast<float>(delta));
    } else if (currentPage == UiPage::RuntimeHome) {
      sendRuntimeOverride(delta > 0 ? 1 : -1);
    } else if (currentPage == UiPage::Home) {
      adjustJogStep(static_cast<int32_t>(delta));
    }
    return true;
  }

  if (line == "ENC_PRESS") {
    if (currentPage == UiPage::RuntimeHome) {
      sendRuntimeOverride(0, true);
    } else if (currentPage == UiPage::Home) {
      toggleJogMode();
    }
    return true;
  }

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
  if (handleRpEvent(line)) {
    return;
  }
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

  drawDisplaySmokeTest("Connecting WiFi...");
  uint32_t startMs = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    if (millis() - startMs > 30000) {
      startMs = millis();
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

  currentPage = UiPage::Home;
  renderPage();
  setLabelText(lblStatus, "Booting...");
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

  loadProbeSettings();
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
  servicePendingStepJog(false);
  lv_timer_handler();
  delay(5);
}
