#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ---------------- WiFi ----------------
const char* WIFI_SSID = "Hersheeysssheree";
const char* WIFI_PASSWORD = "okayokayokay";

// ---------------- MQTT ----------------
const char* MQTT_BROKER = "10.13.139.80";
const int MQTT_PORT = 1883;
const char* MQTT_TOPIC = "smartguard/sensors";

// ---------------- DHT22 ----------------
#define DHT1_PIN 18
#define DHT2_PIN 5
#define DHT3_PIN 4

DHT dht1(DHT1_PIN, DHT22);
DHT dht2(DHT2_PIN, DHT22);
DHT dht3(DHT3_PIN, DHT22);

// ---------------- MQ Sensors ----------------
#define MQ2_PIN 34
#define MQ4_PIN 35

// ---------------- LEDs ----------------
#define LED1 21
#define LED2 22
#define LED3 23

// ---------------- Relay ----------------
#define RELAY_FAN_PIN 25

// ---------------- Thresholds ----------------
#define TEMP_WARNING 35.0

#define MQ2_WARNING 1500
#define MQ4_WARNING 1200

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// ------------------------------------------------

void connectWiFi() {

  Serial.print("Connecting WiFi");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.print("WiFi Connected: ");
  Serial.println(WiFi.localIP());
}

// ------------------------------------------------

void connectMQTT() {

  while (!mqtt.connected()) {

    Serial.print("Connecting MQTT...");

    if (mqtt.connect("SmartGuardESP32")) {

      Serial.println("Connected");

    } else {

      Serial.print("Failed, rc=");
      Serial.println(mqtt.state());

      delay(2000);
    }
  }
}

// ------------------------------------------------

void setup() {

  Serial.begin(115200);

  dht1.begin();
  dht2.begin();
  dht3.begin();

  pinMode(LED1, OUTPUT);
  pinMode(LED2, OUTPUT);
  pinMode(LED3, OUTPUT);

  pinMode(RELAY_FAN_PIN, OUTPUT);

  digitalWrite(LED1, HIGH);
  digitalWrite(LED2, HIGH);
  digitalWrite(LED3, HIGH);

  digitalWrite(RELAY_FAN_PIN, HIGH);

  connectWiFi();

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);

  connectMQTT();

  Serial.println("SmartGuard Started");
}

// ------------------------------------------------

void loop() {

  if (!mqtt.connected()) {
    connectMQTT();
  }

  mqtt.loop();

  // ---------- DHT ----------
  float t1 = dht1.readTemperature();
  float h1 = dht1.readHumidity();

  float t2 = dht2.readTemperature();
  float h2 = dht2.readHumidity();

  float t3 = dht3.readTemperature();
  float h3 = dht3.readHumidity();

  if (isnan(t1)) t1 = -1;
  if (isnan(h1)) h1 = -1;

  if (isnan(t2)) t2 = -1;
  if (isnan(h2)) h2 = -1;

  if (isnan(t3)) t3 = -1;
  if (isnan(h3)) h3 = -1;

  // ---------- MQ ----------
  int mq2 = analogRead(MQ2_PIN);
  int mq4 = analogRead(MQ4_PIN);

  float maxTemp = max(t1, max(t2, t3));

  bool tempDanger = (maxTemp >= TEMP_WARNING);

  bool gasDanger =
      (mq2 > MQ2_WARNING) ||
      (mq4 > MQ4_WARNING);

  bool danger =
      tempDanger ||
      gasDanger;

  // ---------- LEDs ----------
  if (danger) {

    digitalWrite(LED1, LOW);
    digitalWrite(LED2, LOW);
    digitalWrite(LED3, LOW);

  } else {

    digitalWrite(LED1, HIGH);
    digitalWrite(LED2, HIGH);
    digitalWrite(LED3, HIGH);
  }

  // ---------- Relay ----------
  if (tempDanger) {

    digitalWrite(RELAY_FAN_PIN, LOW);

  } else {

    digitalWrite(RELAY_FAN_PIN, HIGH);
  }

  // ---------- MQTT JSON ----------
  StaticJsonDocument<512> doc;

  doc["t1"] = t1;
  doc["h1"] = h1;

  doc["t2"] = t2;
  doc["h2"] = h2;

  doc["t3"] = t3;
  doc["h3"] = h3;

  doc["mq2"] = mq2;
  doc["mq4"] = mq4;

  doc["maxTemp"] = maxTemp;

  doc["fan"] = tempDanger ? "ON" : "OFF";

  doc["status"] = danger ? "DANGER" : "SAFE";

  doc["tempWarning"] = tempDanger;
  doc["gasWarning"] = gasDanger;

  char payload[512];

  serializeJson(doc, payload);

  mqtt.publish(MQTT_TOPIC, payload);

  // ---------- Serial ----------
  Serial.println("--------------------------------");

  Serial.print("T1: ");
  Serial.println(t1);

  Serial.print("T2: ");
  Serial.println(t2);

  Serial.print("T3: ");
  Serial.println(t3);

  Serial.print("MQ2: ");
  Serial.println(mq2);

  Serial.print("MQ4: ");
  Serial.println(mq4);

  Serial.print("Max Temp: ");
  Serial.println(maxTemp);

  Serial.print("Fan: ");
  Serial.println(tempDanger ? "ON" : "OFF");

  Serial.print("Status: ");
  Serial.println(danger ? "DANGER" : "SAFE");

  delay(1000);
}