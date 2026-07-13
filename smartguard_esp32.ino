#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ======================================================
// SMARTGUARD
// TRANSFORMER HEALTH MONITORING SYSTEM
// ESP32 + RASPBERRY PI + MQTT
// ======================================================


// ======================================================
// WiFi Configuration
// ======================================================

const char* WIFI_SSID = "Hersheeysssheree";
const char* WIFI_PASSWORD = "okayokayokay";


// ======================================================
// MQTT Configuration
// ======================================================

const char* MQTT_BROKER = "10.17.46.80";
const int MQTT_PORT = 1883;
const char* MQTT_TOPIC = "smartguard/sensors";


// ======================================================
// DHT22 Sensors
// ======================================================

#define DHTTYPE DHT22

#define DHT1_PIN 18
#define DHT2_PIN 5
#define DHT3_PIN 4

DHT dht1(DHT1_PIN, DHTTYPE);
DHT dht2(DHT2_PIN, DHTTYPE);
DHT dht3(DHT3_PIN, DHTTYPE);


// ======================================================
// MQ Gas Sensors
// ======================================================

#define MQ2_PIN 34
#define MQ4_PIN 35


// ======================================================
// LEDs
// ======================================================

#define RED_LED     21
#define YELLOW_LED  22
#define GREEN_LED   23


// ======================================================
// Relay Module
// ======================================================

#define RELAY_BULB 25
#define RELAY_FAN  26


// ======================================================
// Thresholds
// ======================================================

const float TEMP_THRESHOLD = 55.80;

const int MQ2_THRESHOLD = 100;
const int MQ4_THRESHOLD = 370;


// ======================================================
// WiFi and MQTT Objects
// ======================================================

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);


// ======================================================
// Connect to WiFi
// ======================================================

void connectWiFi()
{
  Serial.println();
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;

  while (WiFi.status() != WL_CONNECTED && attempts < 20)
  {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println("WiFi Connected!");
    Serial.print("ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  }
  else
  {
    Serial.println("WiFi connection failed.");
    Serial.println("Sensor monitoring will continue.");
  }
}


// ======================================================
// Connect to MQTT Broker
// ======================================================

void connectMQTT()
{
  if (WiFi.status() != WL_CONNECTED)
  {
    return;
  }

  Serial.print("Connecting to MQTT Broker: ");
  Serial.println(MQTT_BROKER);

  int attempts = 0;

  while (!mqttClient.connected() && attempts < 3)
  {
    String clientId = "SmartGuardESP32-";
    clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

    if (mqttClient.connect(clientId.c_str()))
    {
      Serial.println("MQTT Connected!");
    }
    else
    {
      Serial.print("MQTT connection failed. State: ");
      Serial.println(mqttClient.state());

      attempts++;
      delay(1000);
    }
  }

  if (!mqttClient.connected())
  {
    Serial.println("MQTT unavailable.");
    Serial.println("Local monitoring will continue.");
  }
}


// ======================================================
// SETUP
// ======================================================

void setup()
{
  Serial.begin(115200);
  delay(1000);

  dht1.begin();
  dht2.begin();
  dht3.begin();

  pinMode(RED_LED, OUTPUT);
  pinMode(YELLOW_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);

  pinMode(RELAY_BULB, OUTPUT);
  pinMode(RELAY_FAN, OUTPUT);

  digitalWrite(RELAY_BULB, LOW);   // Bulbs ON
  digitalWrite(RELAY_FAN, HIGH);   // Fan OFF

  digitalWrite(GREEN_LED, HIGH);
  digitalWrite(YELLOW_LED, LOW);
  digitalWrite(RED_LED, LOW);

  Serial.println();
  Serial.println("==========================================");
  Serial.println(" SMARTGUARD");
  Serial.println(" TRANSFORMER HEALTH MONITORING SYSTEM");
  Serial.println("==========================================");

  Serial.print("Temperature Threshold : ");
  Serial.print(TEMP_THRESHOLD);
  Serial.println(" C");

  Serial.print("MQ2 Threshold         : ");
  Serial.println(MQ2_THRESHOLD);

  Serial.print("MQ4 Threshold         : ");
  Serial.println(MQ4_THRESHOLD);

  Serial.print("MQTT Topic            : ");
  Serial.println(MQTT_TOPIC);

  Serial.println("==========================================");

  connectWiFi();

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setBufferSize(1024);   // <-- FIX 1: increase MQTT buffer size

  connectMQTT();

  Serial.println();
  Serial.println("SmartGuard System Started");
  Serial.println();
}


// ======================================================
// MAIN LOOP
// ======================================================

void loop()
{
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("WiFi disconnected. Attempting reconnection...");
    connectWiFi();
  }

  if (WiFi.status() == WL_CONNECTED)
  {
    if (!mqttClient.connected())
    {
      connectMQTT();
    }

    mqttClient.loop();
  }

  // ---------------- Read DHT22 Sensors ----------------

  float t1 = dht1.readTemperature();
  float h1 = dht1.readHumidity();

  float t2 = dht2.readTemperature();
  float h2 = dht2.readHumidity();

  float t3 = dht3.readTemperature();
  float h3 = dht3.readHumidity();

  bool dht1Valid = !isnan(t1);
  bool dht2Valid = !isnan(t2);
  bool dht3Valid = !isnan(t3);

  float maxTemp = -100.0;
  bool anyTemperatureValid = false;

  if (dht1Valid)
  {
    maxTemp = t1;
    anyTemperatureValid = true;
  }

  if (dht2Valid)
  {
    if (!anyTemperatureValid || t2 > maxTemp)
    {
      maxTemp = t2;
    }
    anyTemperatureValid = true;
  }

  if (dht3Valid)
  {
    if (!anyTemperatureValid || t3 > maxTemp)
    {
      maxTemp = t3;
    }
    anyTemperatureValid = true;
  }

  // ---------------- Read MQ Sensors ----------------

  int mq2 = analogRead(MQ2_PIN);
  int mq4 = analogRead(MQ4_PIN);

  // ---------------- Fault Detection ----------------

  bool tempFault = false;

  if (anyTemperatureValid)
  {
    tempFault = (maxTemp >= TEMP_THRESHOLD);
  }

  bool gasFault =
      (mq2 >= MQ2_THRESHOLD) ||
      (mq4 >= MQ4_THRESHOLD);

  // ---------------- System State ----------------

  String systemStatus;
  String faultType;
  String ledStatus;
  String bulbStatus;
  String fanStatus;

  if (gasFault)
  {
    digitalWrite(RELAY_BULB, HIGH);   // Bulbs OFF
    digitalWrite(RELAY_FAN, HIGH);    // Fan OFF

    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, HIGH);

    systemStatus = "CRITICAL";
    ledStatus = "RED";
    bulbStatus = "OFF";
    fanStatus = "OFF";

    if (tempFault)
    {
      faultType = "HIGH_TEMPERATURE_AND_GAS";
    }
    else
    {
      faultType = "GAS_DETECTED";
    }
  }
  else if (tempFault)
  {
    digitalWrite(RELAY_BULB, LOW);    // Bulbs ON
    digitalWrite(RELAY_FAN, LOW);     // Fan ON

    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, HIGH);
    digitalWrite(RED_LED, LOW);

    systemStatus = "WARNING";
    faultType = "HIGH_TEMPERATURE";
    ledStatus = "YELLOW";
    bulbStatus = "ON";
    fanStatus = "ON";
  }
  else
  {
    digitalWrite(RELAY_BULB, LOW);    // Bulbs ON
    digitalWrite(RELAY_FAN, HIGH);    // Fan OFF

    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, LOW);

    systemStatus = "NORMAL";
    faultType = "NONE";
    ledStatus = "GREEN";
    bulbStatus = "ON";
    fanStatus = "OFF";
  }

  // ---------------- Serial Monitor Output ----------------

  Serial.println("------------------------------------------");

  Serial.print("Temperature 1 : ");
  if (dht1Valid) { Serial.print(t1, 2); Serial.println(" C"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.print("Humidity 1    : ");
  if (!isnan(h1)) { Serial.print(h1, 2); Serial.println(" %"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.print("Temperature 2 : ");
  if (dht2Valid) { Serial.print(t2, 2); Serial.println(" C"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.print("Humidity 2    : ");
  if (!isnan(h2)) { Serial.print(h2, 2); Serial.println(" %"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.print("Temperature 3 : ");
  if (dht3Valid) { Serial.print(t3, 2); Serial.println(" C"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.print("Humidity 3    : ");
  if (!isnan(h3)) { Serial.print(h3, 2); Serial.println(" %"); }
  else { Serial.println("SENSOR READ ERROR"); }

  Serial.println();
  Serial.print("MQ2 : ");
  Serial.println(mq2);
  Serial.print("MQ4 : ");
  Serial.println(mq4);

  Serial.println();
  Serial.print("Maximum Temperature : ");
  if (anyTemperatureValid) { Serial.print(maxTemp, 2); Serial.println(" C"); }
  else { Serial.println("NO VALID TEMPERATURE DATA"); }

  Serial.println();
  Serial.print("Temperature Fault : ");
  Serial.println(tempFault ? "YES" : "NO");
  Serial.print("Gas Fault         : ");
  Serial.println(gasFault ? "YES" : "NO");

  Serial.println();
  Serial.print("System Status : ");
  Serial.println(systemStatus);
  Serial.print("Fault Type    : ");
  Serial.println(faultType);
  Serial.print("LED           : ");
  Serial.println(ledStatus);
  Serial.print("Bulbs         : ");
  Serial.println(bulbStatus);
  Serial.print("Fan           : ");
  Serial.println(fanStatus);

  // ---------------- Build MQTT JSON ----------------

  StaticJsonDocument<768> doc;

  doc["t1"] = dht1Valid ? t1 : (float)NAN;
  doc["t2"] = dht2Valid ? t2 : (float)NAN;
  doc["t3"] = dht3Valid ? t3 : (float)NAN;

  if (dht1Valid) doc["t1"] = t1; else doc["t1"] = nullptr;
  if (dht2Valid) doc["t2"] = t2; else doc["t2"] = nullptr;
  if (dht3Valid) doc["t3"] = t3; else doc["t3"] = nullptr;

  if (!isnan(h1)) doc["h1"] = h1; else doc["h1"] = nullptr;
  if (!isnan(h2)) doc["h2"] = h2; else doc["h2"] = nullptr;
  if (!isnan(h3)) doc["h3"] = h3; else doc["h3"] = nullptr;

  doc["mq2"] = mq2;
  doc["mq4"] = mq4;

  if (anyTemperatureValid) doc["maxTemp"] = maxTemp; else doc["maxTemp"] = nullptr;

  doc["tempThreshold"] = TEMP_THRESHOLD;
  doc["mq2Threshold"] = MQ2_THRESHOLD;
  doc["mq4Threshold"] = MQ4_THRESHOLD;

  doc["tempFault"] = tempFault;
  doc["gasFault"] = gasFault;

  doc["status"] = systemStatus;
  doc["faultType"] = faultType;
  doc["led"] = ledStatus;
  doc["bulbs"] = bulbStatus;
  doc["fan"] = fanStatus;

  // ---------------- Publish MQTT Data ----------------
  // FIX 2: use serialized length + byte-array publish + state logging

  char payload[768];
  size_t len = serializeJson(doc, payload);

  Serial.print("JSON Length: ");
  Serial.println(len);

  mqttClient.loop();

  if (mqttClient.connected())
  {
    bool published = mqttClient.publish(
        MQTT_TOPIC,
        (uint8_t*)payload,
        len
    );

    Serial.print("MQTT State: ");
    Serial.println(mqttClient.state());

    if (published)
    {
      Serial.println();
      Serial.println("MQTT Publish: SUCCESS");
      Serial.print("Topic: ");
      Serial.println(MQTT_TOPIC);
      Serial.print("Payload: ");
      Serial.println(payload);
    }
    else
    {
      Serial.println();
      Serial.println("MQTT Publish: FAILED");
    }
  }
  else
  {
    Serial.println();
    Serial.println("MQTT: NOT CONNECTED");
    Serial.println("Local monitoring is still running.");
  }

  Serial.println("------------------------------------------");
  Serial.println();

  delay(20000);
}