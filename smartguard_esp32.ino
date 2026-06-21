/*
 * SmartGuard Dry Transformer Monitor
 * ESP32 Firmware — Full Build (DHT11 x3 + MQ2/4/7 + SW-420 + Relay + LED)
 *
 * Sensors:
 *   - 3x DHT11  (temperature + humidity)
 *   - MQ2       (smoke)
 *   - MQ4       (methane / flammable gas)
 *   - MQ7       (carbon monoxide)
 *   - SW-420    (vibration)
 *
 * Actuators:
 *   - 2-channel relay: CH1 = cooling fan, CH2 = power-cut (isolation)
 *   - 1x red LED (fault indicator, GPIO21)
 *
 * Publishes JSON to MQTT topic: smartguard/sensors  (every 1 second)
 *
 * Dependencies (install via Arduino Library Manager):
 *   - DHT sensor library by Adafruit
 *   - Adafruit Unified Sensor
 *   - PubSubClient by Nick O'Leary
 *   - ArduinoJson by Benoit Blanchon
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ─── WiFi & MQTT ───────────────────────────────────────────────────────────
const char* WIFI_SSID     = "Hersheeysssheree";
const char* WIFI_PASSWORD = "okayokayokay";
const char* MQTT_BROKER   = "10.13.139.80";   // Raspberry Pi IP
const int   MQTT_PORT     = 1883;
const char* MQTT_CLIENT   = "smartguard-esp32";

// ─── Pin Definitions ───────────────────────────────────────────────────────
#define DHT_PIN_1   18    // Winding 1 area (wired here)
#define DHT_PIN_2   5    // Winding 2 area
#define DHT_PIN_3   4   // Ambient / casing

#define MQ2_PIN     34    // Smoke       (ADC1)
#define MQ4_PIN     35    // Methane     (ADC1)
#define MQ7_PIN     32    // CO          (ADC1)

#define SW420_PIN   27    // Vibration (digital)

#define RELAY_FAN_PIN    25   // Relay CH1 — cooling fan
#define RELAY_POWER_PIN  26   // Relay CH2 — power-cut / isolation

#define LED_PIN     21    // Single red fault LED

// Most relay modules are active-LOW (LOW = relay energized/ON).
// Set to false if your module is active-HIGH instead.
#define RELAY_ACTIVE_LOW  true

// ─── Thresholds (tune after reading idle values on Serial Monitor) ─────────
#define MQ2_THRESHOLD   1500
#define MQ4_THRESHOLD   1200
#define MQ7_THRESHOLD   1000

#define TEMP_WARNING    55.0
#define TEMP_CRITICAL   70.0

// SW-420 sends rapid digital pulses while vibrating; we count pulses in a
// rolling window rather than trusting a single instantaneous read.
#define VIBE_WINDOW_MS      500
#define VIBE_PULSE_THRESHOLD 2

// ─── Timing ────────────────────────────────────────────────────────────────
#define PUBLISH_INTERVAL_MS  1000

// ─── Globals ───────────────────────────────────────────────────────────────
DHT dht1(DHT_PIN_1, DHT22);
DHT dht2(DHT_PIN_2, DHT22);
DHT dht3(DHT_PIN_3, DHT22);

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastPublish = 0;

// Vibration pulse counting
volatile unsigned long vibePulseCount = 0;
unsigned long vibeWindowStart = 0;
bool vibrationDetected = false;

// Last commanded actuator states (so we don't spam digitalWrite every loop)
bool fanOn = false;
bool powerCutOn = false;

void IRAM_ATTR onVibePulse() {
  vibePulseCount++;
}

// ─── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  dht1.begin();
  dht2.begin();
  dht3.begin();

  pinMode(SW420_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(SW420_PIN), onVibePulse, RISING);
  vibeWindowStart = millis();

  pinMode(RELAY_FAN_PIN, OUTPUT);
  pinMode(RELAY_POWER_PIN, OUTPUT);
  setRelay(RELAY_FAN_PIN, false);
  setRelay(RELAY_POWER_PIN, false);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(LED_PIN, HIGH);

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

  // Evaluate vibration window independently of publish cycle, so LED/flag
  // react in real time instead of waiting up to 1s for the next publish.
  if (millis() - vibeWindowStart >= VIBE_WINDOW_MS) {
    unsigned long count = vibePulseCount;
    vibrationDetected = (count >= VIBE_PULSE_THRESHOLD);
    Serial.printf("[VIB] pulses=%lu  threshold=%d  detected=%d\n",
                  count, VIBE_PULSE_THRESHOLD, vibrationDetected);
    vibePulseCount = 0;
    vibeWindowStart = millis();
    updateLED();
  }

  if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = millis();
    readAndPublish();
  }
}

// ─── LED Helper ────────────────────────────────────────────────────────────
// Re-evaluates all fault flags (using latest known sensor state) and drives
// the LED. Called both from the vibration window tick and from
// readAndPublish(), so the LED reacts to whichever condition changes first.
bool lastSmoke = false, lastGas = false, lastCo = false;
bool lastHeatWarn = false, lastHeatCrit = false;

void updateLED() {
  bool anyFault = lastSmoke || lastGas || lastCo ||
                  lastHeatWarn || lastHeatCrit || vibrationDetected;
  digitalWrite(LED_PIN, anyFault ? HIGH : LOW);
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

  // Cache for updateLED(), which also runs from the vibration window tick
  lastSmoke = smokeDetected; lastGas = gasDetected; lastCo = coWarning;
  lastHeatWarn = heatWarning; lastHeatCrit = heatCritical;

  // ── Actuator logic ──
  // Fan: turn on for heat warning OR critical (helps cool while other
  // protections engage)
  bool wantFan = heatWarning || heatCritical;

  // Power-cut: trip on smoke, gas, CO, or critical heat — the serious faults
  bool wantPowerCut = smokeDetected || gasDetected || coWarning || heatCritical;

  if (wantFan != fanOn) {
    setRelay(RELAY_FAN_PIN, wantFan);
    fanOn = wantFan;
  }
  if (wantPowerCut != powerCutOn) {
    setRelay(RELAY_POWER_PIN, wantPowerCut);
    powerCutOn = wantPowerCut;
  }

  // LED: on for any fault condition (smoke/gas/co/heat/vibration)
  updateLED();

  // Build JSON
  StaticJsonDocument<500> doc;
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
  flags["vibration"]     = vibrationDetected;

  JsonObject actuators = doc.createNestedObject("actuators");
  actuators["fan_on"]        = fanOn;
  actuators["power_cut_on"]  = powerCutOn;

  char buf[500];
  serializeJson(doc, buf);
  mqtt.publish("smartguard/sensors", buf);

  // Serial debug
  Serial.printf("[T] %.1f | %.1f | %.1f  [MQ] %d | %d | %d  [VIB] %d  [FAN] %d  [CUT] %d\n",
                t1, t2, t3, mq2, mq4, mq7, vibrationDetected, fanOn, powerCutOn);
}

// ─── Relay Helper ──────────────────────────────────────────────────────────
void setRelay(int pin, bool energize) {
  bool level = RELAY_ACTIVE_LOW ? !energize : energize;
  digitalWrite(pin, level ? HIGH : LOW);
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
