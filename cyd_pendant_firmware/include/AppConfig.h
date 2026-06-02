#pragma once

// WiFi credentials (hardcoded for now).
static const char* WIFI_SSID = "REMOVED_WIFI_SSID";
static const char* WIFI_PASS = "REMOVED_WIFI_PASS";

// Device identity.
static const char* DEVICE_HOSTNAME = "cyd-pendant";

// Socket settings. The controller currently acts as TCP client and connects
// to the pendant's server.
static const uint16_t PENDANT_TCP_PORT = 9876;

// Button pins (active-low). Update for your wiring.
static const int PIN_BTN_CONFIRM = 0;
static const int PIN_BTN_CLAMP = 35;
static const int PIN_BTN_UNCLAMP = 34;

// RP2040 UART link. Defaults are ESP32 Serial2 pins; update if your CYD header
// labels map to different GPIOs.
static const int PIN_RP_UART_RX = 35;  // CYD receives from RP2040 TX.
static const int PIN_RP_UART_TX = 22;  // CYD transmits to RP2040 RX.
static const uint32_t RP_UART_BAUD = 115200;
