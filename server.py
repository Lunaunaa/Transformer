from flask import Flask, jsonify
from flask_cors import CORS

import json
import paho.mqtt.client as mqtt

app = Flask(__name__)
CORS(app)

latest_data = {
    "t1": 0,
    "h1": 0,
    "t2": 0,
    "h2": 0,
    "t3": 0,
    "h3": 0,
    "mq2": 0,
    "mq4": 0,
    "maxTemp": 0,
    "fan": "OFF",
    "status": "WAITING",
    "tempWarning": False,
    "gasWarning": False
}

# ---------------- MQTT ----------------

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT Broker")
    client.subscribe("smartguard/sensors")

def on_message(client, userdata, msg):
    global latest_data

    try:
        payload = msg.payload.decode()

        latest_data = json.loads(payload)

        print("\n----------------------")
        print("NEW SENSOR DATA")
        print(json.dumps(latest_data, indent=2))

    except Exception as e:
        print("MQTT Error:", e)

mqtt_client = mqtt.Client()

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

mqtt_client.connect("localhost", 1883, 60)

mqtt_client.loop_start()

# ---------------- API ----------------

@app.route("/api/data")
def get_data():
    return jsonify(latest_data)

@app.route("/")
def home():
    return jsonify({
        "message": "SmartGuard API Running",
        "endpoint": "/api/data"
    })

# ---------------- MAIN ----------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )