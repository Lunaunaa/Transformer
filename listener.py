import json
from collections import deque

import paho.mqtt.client as mqtt

# =====================================================
# MQTT
# =====================================================

BROKER = "localhost"
PORT = 1883

SUB_TOPIC = "smartguard/sensors"
PUB_TOPIC = "smartguard/processed"

# =====================================================
# HISTORY FOR TREND ANALYSIS
# =====================================================

temp_history = deque(maxlen=10)
mq2_history = deque(maxlen=10)
mq4_history = deque(maxlen=10)

# =====================================================
# HEALTH SCORE
# =====================================================

def calculate_health(max_temp, mq2, mq4,
                     temp_warning, gas_warning):

    score = 100

    if temp_warning:
        score -= 25

    if gas_warning:
        score -= 25

    if max_temp > 30:
        score -= int((max_temp - 30) * 2)

    if mq2 > 1000:
        score -= min(15, (mq2 - 1000) // 100)

    if mq4 > 800:
        score -= min(15, (mq4 - 800) // 100)

    score = max(0, min(100, score))

    return score

# =====================================================
# FAULT ORIGIN
# =====================================================

def get_origin(t1, t2, t3):

    hottest = max(t1, t2, t3)

    if hottest == t1:
        return "Winding 1"

    elif hottest == t2:
        return "Winding 2"

    return "Transformer Casing"

# =====================================================
# TREND PREDICTION
# =====================================================

def get_prediction():

    if len(temp_history) < 10:
        return (
            "Operating normally.",
            "Collecting baseline data."
        )

    temp_rise = temp_history[-1] - temp_history[0]
    mq2_rise = mq2_history[-1] - mq2_history[0]
    mq4_rise = mq4_history[-1] - mq4_history[0]

    insight = "Operating normally."
    prediction = "Stable conditions."

    # Combined trend

    if temp_rise > 1.0 and (mq2_rise > 300 or mq4_rise > 300):

        insight = (
            "Temperature and gas levels are rising together."
        )

        prediction = (
            "Early-stage thermal stress may be developing."
        )

    elif mq2_rise > 300:

        insight = (
            "Smoke/VOC concentration increasing steadily."
        )

        prediction = (
            "Potential overheating condition developing."
        )

    elif mq4_rise > 300:

        insight = (
            "Gas concentration increasing steadily."
        )

        prediction = (
            "Thermal fault indicators are rising."
        )

    elif temp_rise > 1.0:

        insight = (
            "Temperature increasing steadily."
        )

        prediction = (
            "Hotspot formation may occur if trend continues."
        )

    return insight, prediction

# =====================================================
# MESSAGE HANDLER
# =====================================================

def on_connect(client, userdata, flags, rc):

    if rc == 0:
        print("\n[MQTT] Connected")
        client.subscribe(SUB_TOPIC)
        print(f"[MQTT] Subscribed -> {SUB_TOPIC}")

    else:
        print(f"[MQTT] Connection failed: {rc}")

# =====================================================

def on_message(client, userdata, msg):

    try:

        payload = json.loads(msg.payload.decode())

        t1 = payload.get("t1", 0)
        h1 = payload.get("h1", 0)

        t2 = payload.get("t2", 0)
        h2 = payload.get("h2", 0)

        t3 = payload.get("t3", 0)
        h3 = payload.get("h3", 0)

        mq2 = payload.get("mq2", 0)
        mq4 = payload.get("mq4", 0)

        max_temp = payload.get("maxTemp", 0)

        status = payload.get("status", "SAFE")

        temp_warning = payload.get(
            "tempWarning",
            False
        )

        gas_warning = payload.get(
            "gasWarning",
            False
        )

        fan = payload.get("fan", "OFF")

        # -------------------------------------
        # HISTORY
        # -------------------------------------

        temp_history.append(max_temp)
        mq2_history.append(mq2)
        mq4_history.append(mq4)

        # -------------------------------------
        # ANALYSIS
        # -------------------------------------

        health = calculate_health(
            max_temp,
            mq2,
            mq4,
            temp_warning,
            gas_warning
        )

        origin = get_origin(
            t1,
            t2,
            t3
        )

        insight, prediction = get_prediction()

        # Override prediction only after
        # actual threshold is crossed

        if temp_warning:

            insight = (
                "Temperature threshold exceeded."
            )

            prediction = (
                "Overheating detected. Cooling recommended."
            )

        if gas_warning:

            insight = (
                "Gas threshold exceeded."
            )

            prediction = (
                "Thermal fault likely. Inspection recommended."
            )

        processed = {

            "status": status,
            "health": health,

            "origin": origin,

            "insight": insight,
            "prediction": prediction,

            "t1": t1,
            "t2": t2,
            "t3": t3,

            "h1": h1,
            "h2": h2,
            "h3": h3,

            "mq2": mq2,
            "mq4": mq4,

            "fan": fan
        }

        client.publish(
            PUB_TOPIC,
            json.dumps(processed)
        )

        # =====================================
        # TERMINAL OUTPUT
        # =====================================

        print("\n" + "=" * 55)
        print(" SMARTGUARD TRANSFORMER MONITOR ")
        print("=" * 55)

        print(
            f"T1={t1:.1f}°C  "
            f"T2={t2:.1f}°C  "
            f"T3={t3:.1f}°C"
        )

        print(
            f"H1={h1:.1f}%  "
            f"H2={h2:.1f}%  "
            f"H3={h3:.1f}%"
        )

        print(
            f"MQ2={mq2}   MQ4={mq4}"
        )

        print()

        print(f"Status      : {status}")
        print(f"Health      : {health}/100")
        print(f"Origin      : {origin}")
        print(f"Fan         : {fan}")

        print()
        print(f"Insight     : {insight}")
        print(f"Prediction  : {prediction}")

    except Exception as e:

        print(f"[ERROR] {e}")

# =====================================================
# MAIN
# =====================================================

client = mqtt.Client()

client.on_connect = on_connect
client.on_message = on_message

print(
    f"[SmartGuard] Connecting to "
    f"{BROKER}:{PORT}"
)

client.connect(BROKER, PORT, 60)

client.loop_forever()