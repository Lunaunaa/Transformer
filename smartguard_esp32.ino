#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ─── WiFi & MQTT ───────────────────────────────────────────────────────────
const char* WIFI_SSID     = "Hersheeysssheree";
const char* WIFI_PASSWORD = "okayokayokay";
const char* MQTT_BROKER   = "10.236.235.80";   // Raspberry Pi IP
const int   MQTT_PORT     = 1883;
const char* MQTT_CLIENT   = "smartguard-esp32";

// ─── Pin Definitions ───────────────────────────────────────────────────────
#define DHT_PIN_1 4
#define DHT_PIN_2 5
#define DHT_PIN_3 15  // Ambient / casing

#define MQ2_PIN     34    // Smoke       (ADC1)
#define MQ4_PIN     35    // Methane     (ADC1)
#define MQ7_PIN     32    // CO          (ADC1)

// ─── Thresholds (tune after reading idle values on Serial Monitor) ─────────
#define MQ2_THRESHOLD   1500
#define MQ4_THRESHOLD   1200
#define MQ7_THRESHOLD   1000

#define TEMP_WARNING    55.0
#define TEMP_CRITICAL   70.0

// ─── Timing ────────────────────────────────────────────────────────────────
#define PUBLISH_INTERVAL_MS  1000

// ─── Globals ───────────────────────────────────────────────────────────────
DHT dht1(DHT_PIN_1, DHT11);
DHT dht2(DHT_PIN_2, DHT11);
DHT dht3(DHT_PIN_3, DHT11);

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastPublish = 0;

// ─── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  dht1.begin();
  dht2.begin();
  dht3.begin();

  connectWiFi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setBufferSize(512);
  connectMQTT();

  Serial.println("[SmartGuard] Boot complete");
}

// ─── Main Loop ─────────────────────────────────────────────────────────────
void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = millis();
    readAndPublish();
  }
}

// ─── Read Sensors → Publish ────────────────────────────────────────────────
void readAndPublish() {

  // DHT11 readings
  float t1 = dht1.readTemperature();
  float h1 = dht1.readHumidity();
  float t2 = dht2.readTemperature();
  float h2 = dht2.readHumidity();
  float t3 = dht3.readTemperature();
  float h3 = dht3.readHumidity();

  // Replace NaN with -1
  if (isnan(t1)) t1 = -1; if (isnan(h1)) h1 = -1;
  if (isnan(t2)) t2 = -1; if (isnan(h2)) h2 = -1;
  if (isnan(t3)) t3 = -1; if (isnan(h3)) h3 = -1;

  float maxTemp = max({t1, t2, t3});

  // MQ sensor raw ADC readings
  int mq2 = analogRead(MQ2_PIN);
  int mq4 = analogRead(MQ4_PIN);
  int mq7 = analogRead(MQ7_PIN);

  // Derive simple local flags (Pi does deeper analysis)
  bool smokeDetected = (mq2 > MQ2_THRESHOLD);
  bool gasDetected   = (mq4 > MQ4_THRESHOLD);
  bool coWarning     = (mq7 > MQ7_THRESHOLD);
  bool heatWarning   = (maxTemp >= TEMP_WARNING && maxTemp < TEMP_CRITICAL);
  bool heatCritical  = (maxTemp >= TEMP_CRITICAL);

  // Build JSON
  StaticJsonDocument<400> doc;
  doc["ts"]       = millis();

  JsonObject temp = doc.createNestedObject("temp");
  temp["t1"]  = t1;
  temp["t2"]  = t2;
  temp["t3"]  = t3;
  temp["max"] = maxTemp;

  JsonObject hum = doc.createNestedObject("humidity");
  hum["h1"] = h1;
  hum["h2"] = h2;
  hum["h3"] = h3;

  JsonObject gas = doc.createNestedObject("gas");
  gas["mq2"] = mq2;
  gas["mq4"] = mq4;
  gas["mq7"] = mq7;

  JsonObject flags = doc.createNestedObject("flags");
  flags["smoke"]         = smokeDetected;
  flags["gas"]           = gasDetected;
  flags["co"]            = coWarning;
  flags["heat_warning"]  = heatWarning;
  flags["heat_critical"] = heatCritical;

  char buf[400];
  serializeJson(doc, buf);
  mqtt.publish("smartguard/sensors", buf);

  // Serial debug
  Serial.printf("[T] %.1f | %.1f | %.1f  [MQ] %d | %d | %d\n",
                t1, t2, t3, mq2, mq4, mq7);
}

// ─── WiFi ──────────────────────────────────────────────────────────────────
void connectWiFi() {
  Serial.print("[WiFi] Connecting");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.printf("\n[WiFi] Connected: %s\n", WiFi.localIP().toString().c_str());
}

// ─── MQTT ──────────────────────────────────────────────────────────────────
void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("[MQTT] Connecting...");
    if (mqtt.connect(MQTT_CLIENT)) {
      Serial.println(" OK");
    } else {
      Serial.printf(" failed rc=%d, retry in 3s\n", mqtt.state());
      delay(3000);
    }
  }
}
