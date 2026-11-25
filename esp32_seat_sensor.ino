
#include <WiFi.h>
#include <HTTPClient.h>
#include "HX711.h"

// ==================== Wi-Fi 配置 ====================

// Replace these placeholders locally. Never commit real credentials.
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// ==================== Flask 服务器配置 ====================

const char* serverUrl = "http://YOUR_SERVER_IP:5000/api/sensor";

// 当前设备编号
const char* deviceId = "seat_04";

// ==================== HX711 引脚配置 ====================

const int DT_PIN = 16;
const int SCK_PIN = 17;

HX711 scale;

// ==================== 数据配置 ====================

unsigned long sequenceNumber = 0;

const unsigned long sendInterval = 1000;

unsigned long lastSendTime = 0;


// ==================== Wi-Fi 连接函数 ====================

void connectWiFi() {

  Serial.println();
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected successfully!");

  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  Serial.print("Signal Strength (RSSI): ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
}


// ==================== Wi-Fi 重连函数 ====================

void checkWiFi() {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("WiFi disconnected!");
    Serial.println("Reconnecting...");

    WiFi.disconnect();
    WiFi.begin(ssid, password);

    unsigned long startTime = millis();

    while (WiFi.status() != WL_CONNECTED &&
           millis() - startTime < 10000) {
      delay(500);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println();
      Serial.println("WiFi reconnected!");
      Serial.print("IP Address: ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println();
      Serial.println("WiFi reconnection failed!");
    }
  }
}


// ==================== 发送数据到 Flask ====================

void sendData(long rawValue) {

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Cannot send data: WiFi disconnected!");
    return;
  }

  WiFiClient client;
  HTTPClient http;

  // 初始化 HTTP 请求
  if (!http.begin(client, serverUrl)) {
    Serial.println("HTTP connection initialization failed!");
    return;
  }

  http.setTimeout(5000);

  // 设置请求头
  http.addHeader("Content-Type", "application/json");

  // 构造 JSON 数据
  sequenceNumber++;

  String jsonData = "{";
  jsonData += "\"device_id\":\"";
  jsonData += deviceId;
  jsonData += "\",";
  jsonData += "\"raw_value\":";
  jsonData += String(rawValue);
  jsonData += ",";
  jsonData += "\"sequence\":";
  jsonData += String(sequenceNumber);
  jsonData += "}";

  // 发送 POST 请求
  Serial.println("--------------------------------");

  Serial.print("Device ID: ");
  Serial.println(deviceId);

  Serial.print("Sequence: ");
  Serial.println(sequenceNumber);

  Serial.print("RAW Value: ");
  Serial.println(rawValue);

  Serial.print("Sending JSON: ");
  Serial.println(jsonData);

  int httpResponseCode = http.POST(jsonData);

  // 输出服务器响应
  Serial.print("HTTP Response Code: ");
  Serial.println(httpResponseCode);

  if (httpResponseCode > 0) {

    String response = http.getString();

    Serial.print("Server Response: ");
    Serial.println(response);

    if (httpResponseCode == 200) {
      Serial.println("Data sent successfully!");
    } else {
      Serial.println("Server returned an error!");
    }

  } else {

    Serial.print("HTTP Request failed: ");
    Serial.println(http.errorToString(httpResponseCode));
  }

  http.end();
}


// ==================== Setup ====================

void setup() {

  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("================================");
  Serial.println("Seat Detection ESP32 System");
  Serial.println("================================");

  // 连接 Wi-Fi
  connectWiFi();

  // 初始化 HX711
  Serial.println();
  Serial.println("Initializing HX711...");

  scale.begin(DT_PIN, SCK_PIN);

  if (scale.is_ready()) {
    Serial.println("HX711 initialized successfully!");
  } else {
    Serial.println("Warning: HX711 is not ready!");
  }

  Serial.println();
  Serial.println("System started!");
}


// ==================== Main Loop ====================

void loop() {

  // 检查 Wi-Fi 状态
  checkWiFi();

  // 每隔约 1 秒采集并发送一次
  unsigned long currentTime = millis();

  if (currentTime - lastSendTime >= sendInterval) {

    lastSendTime = currentTime;

    if (scale.is_ready()) {

      // 读取 HX711 原始数据
      long rawValue = scale.read();

      // 发送到 Flask 服务器
      sendData(rawValue);

    } else {

      Serial.println("HX711 is not ready!");
    }
  }
}
