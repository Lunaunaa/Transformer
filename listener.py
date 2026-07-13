#!/usr/bin/env python3

"""
SmartGuard - Edge Diagnostics Processor
listener.py

FLOW:
ESP32
  -> publishes raw sensor data to:
     smartguard/sensors

listener.py
  -> receives raw data
  -> processes transformer condition
  -> calculates health score and diagnostic state
  -> publishes processed data to:
     smartguard/processed

bridge.py
  -> receives smartguard/processed
  -> sends data to website using WebSocket

Run:
    python3 listener.py
"""

import json
import logging
import sys
import paho.mqtt.client as mqtt


# ============================================================
# CONFIGURATION
# ============================================================

# Mosquitto broker is running on the SAME Raspberry Pi,
# therefore "localhost" is correct.

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# ESP32 publishes raw sensor data here
RAW_TOPIC = "smartguard/sensors"

# Processed data is published here for bridge.py
PROCESSED_TOPIC = "smartguard/processed"


# ============================================================
# THRESHOLDS
# ============================================================

# IMPORTANT:
# These must match the thresholds used in your ESP32 code.

TEMP_THRESHOLD = 31.0
MQ2_THRESHOLD = 1800
MQ4_THRESHOLD = 1800


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("SmartGuardListener")


# ============================================================
# HELPER FUNCTION
# ============================================================

def safe_number(value, default):
    """
    Safely convert incoming sensor data to a number.

    If the value is:
    - None
    - missing
    - invalid

    return the supplied default value.
    """

    if value is None:
        return default

    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ============================================================
# MQTT CONNECTION CALLBACK
# ============================================================

def on_connect(client, userdata, flags, rc, *args):

    # Support both paho-mqtt v1.x and v2.x

    if isinstance(rc, int):
        connection_rc = rc
    elif hasattr(rc, "value"):
        connection_rc = rc.value
    else:
        connection_rc = 0 if str(rc) == "Success" else -1


    if connection_rc == 0:

        logger.info("==========================================")
        logger.info("Connected successfully to MQTT broker.")
        logger.info(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
        logger.info("==========================================")

        # Subscribe to ESP32 raw sensor data

        result, mid = client.subscribe(RAW_TOPIC)

        if result == mqtt.MQTT_ERR_SUCCESS:

            logger.info(
                f"Subscribed successfully to raw topic: {RAW_TOPIC}"
            )

        else:

            logger.error(
                f"Failed to subscribe to topic: {RAW_TOPIC}"
            )

    else:

        logger.error(
            f"MQTT connection failed. Status: {rc}"
        )


# ============================================================
# MQTT DISCONNECT CALLBACK
# ============================================================

def on_disconnect(client, userdata, *args):

    logger.warning(
        "Disconnected from MQTT broker. "
        "The MQTT client will attempt to reconnect."
    )


# ============================================================
# MQTT MESSAGE CALLBACK
# ============================================================

def on_message(client, userdata, msg):

    try:

        # ----------------------------------------------------
        # RECEIVE RAW ESP32 PAYLOAD
        # ----------------------------------------------------

        payload_str = msg.payload.decode("utf-8")


        logger.info("")
        logger.info("==========================================")
        logger.info("[MQTT RAW RECEIVED]")
        logger.info(f"Topic   : {msg.topic}")
        logger.info(f"Payload : {payload_str}")
        logger.info("==========================================")


        # ----------------------------------------------------
        # PARSE JSON
        # ----------------------------------------------------

        data = json.loads(payload_str)


        # ====================================================
        # EXTRACT TEMPERATURE VALUES
        # ====================================================

        # Use -100 only internally for failed sensors.
        # The original null value will still be sent to
        # the website.

        t1 = safe_number(data.get("t1"), -100.0)
        t2 = safe_number(data.get("t2"), -100.0)
        t3 = safe_number(data.get("t3"), -100.0)


        # ====================================================
        # EXTRACT HUMIDITY VALUES
        # ====================================================

        h1 = safe_number(data.get("h1"), 0.0)
        h2 = safe_number(data.get("h2"), 0.0)
        h3 = safe_number(data.get("h3"), 0.0)


        # ====================================================
        # EXTRACT MQ SENSOR VALUES
        # ====================================================

        mq2 = int(safe_number(data.get("mq2"), 0))
        mq4 = int(safe_number(data.get("mq4"), 0))


        # ====================================================
        # EXTRACT ACTUAL HARDWARE STATES FROM ESP32
        # ====================================================

        fan_state = str(
            data.get("fan", "OFF")
        ).upper()

        bulb_state = str(
            data.get("bulbs", "ON")
        ).upper()

        led_state = str(
            data.get("led", "GREEN")
        ).upper()


        # ====================================================
        # FIND VALID TEMPERATURE READINGS
        # ====================================================

        valid_temperatures = []


        if t1 > -90.0:
            valid_temperatures.append(t1)


        if t2 > -90.0:
            valid_temperatures.append(t2)


        if t3 > -90.0:
            valid_temperatures.append(t3)


        any_temp_valid = len(valid_temperatures) > 0


        if any_temp_valid:

            max_temp = max(valid_temperatures)

            avg_temp = (
                sum(valid_temperatures)
                / len(valid_temperatures)
            )

        else:

            max_temp = None
            avg_temp = None


        # ====================================================
        # DETERMINE FAULT CONDITIONS
        # ====================================================

        if any_temp_valid:

            temp_fault = (
                max_temp >= TEMP_THRESHOLD
            )

        else:

            temp_fault = False


        gas_fault = (
            mq2 >= MQ2_THRESHOLD
            or
            mq4 >= MQ4_THRESHOLD
        )


        # ====================================================
        # DEFAULT NORMAL STATE
        # ====================================================

        health = 100

        status_code = "SAFE"

        origin = "Transformer Monitoring System"

        insight = "Normal Conditions"

        prediction = (
            "Temperature and gas readings are "
            "within configured thresholds."
        )

        fault_type = "NONE"

        risk_level = "LOW"

        recommendation = (
            "No immediate maintenance required. "
            "Continue normal monitoring."
        )


        # ====================================================
        # CONDITION 1:
        # GAS DETECTED
        #
        # This also includes:
        # HIGH TEMPERATURE + GAS
        #
        # Hardware:
        # RED LED
        # BULBS OFF
        # FAN OFF
        # ====================================================

        if gas_fault:

            status_code = "DANGER"

            risk_level = "CRITICAL"

            origin = "Gas Detection Sensors"


            # ----------------------------------------------
            # HIGH TEMPERATURE + GAS
            # ----------------------------------------------

            if temp_fault:

                health = 10

                insight = "Critical Combined Fault"

                prediction = (
                    "High temperature and gas levels "
                    "have crossed configured thresholds. "
                    "Power supply isolated."
                )

                recommendation = (
                    "Immediate inspection required. "
                    "Do not restore power until the "
                    "transformer system has been checked."
                )

                fault_type = (
                    "HIGH_TEMPERATURE_AND_GAS"
                )


            # ----------------------------------------------
            # GAS ONLY
            # ----------------------------------------------

            else:

                health = 25

                insight = "Gas Detected"

                prediction = (
                    "Gas or smoke level has crossed "
                    "the configured safety threshold. "
                    "Power supply isolated."
                )

                recommendation = (
                    "Immediate inspection of the "
                    "transformer and surrounding area "
                    "is recommended."
                )

                fault_type = "GAS_DETECTED"


        # ====================================================
        # CONDITION 2:
        # HIGH TEMPERATURE ONLY
        #
        # Hardware:
        # YELLOW LED
        # BULBS ON
        # FAN ON
        # ====================================================

        elif temp_fault:

            status_code = "WARNING"

            risk_level = "MEDIUM"

            origin = "Transformer Temperature Sensors"


            # Health decreases gradually as temperature
            # rises above the threshold.
            #
            # Example:
            #
            # 31 C -> approximately 95
            # 35 C -> approximately 75
            # Higher temperature -> minimum 55

            excess_temperature = (
                max_temp - TEMP_THRESHOLD
            )


            health = int(
                max(
                    55,
                    min(
                        95,
                        95 - (
                            excess_temperature * 5
                        )
                    )
                )
            )


            insight = "High Temperature Warning"


            prediction = (
                "Transformer surface temperature has "
                "crossed the configured warning threshold. "
                "Cooling fan activated."
            )


            recommendation = (
                "Continue monitoring temperature. "
                "Maintenance inspection is recommended "
                "if the temperature remains elevated "
                "or continues increasing."
            )


            fault_type = "HIGH_TEMPERATURE"


        # ====================================================
        # CONDITION 3:
        # NORMAL
        #
        # Hardware:
        # GREEN LED
        # BULBS ON
        # FAN OFF
        # ====================================================

        else:

            health = 100

            status_code = "SAFE"

            risk_level = "LOW"

            origin = "Transformer Monitoring System"

            insight = "Normal Conditions"

            prediction = (
                "Temperature and gas readings are "
                "within configured thresholds."
            )

            recommendation = (
                "No immediate maintenance required. "
                "Continue normal monitoring."
            )

            fault_type = "NONE"


        # ====================================================
        # SENSOR ERROR INFORMATION
        # ====================================================

        sensor_errors = []


        if data.get("t1") is None:
            sensor_errors.append("DHT1")


        if data.get("t2") is None:
            sensor_errors.append("DHT2")


        if data.get("t3") is None:
            sensor_errors.append("DHT3")


        # ====================================================
        # CONSTRUCT PROCESSED PAYLOAD
        # ====================================================

        processed_payload = {

            # ----------------------------------------------
            # Overall Diagnostic State
            # ----------------------------------------------

            "status": status_code,

            "health": health,

            "riskLevel": risk_level,

            "origin": origin,

            "insight": insight,

            "prediction": prediction,

            "recommendation": recommendation,

            "faultType": fault_type,


            # ----------------------------------------------
            # Temperature
            # ----------------------------------------------

            "t1": data.get("t1"),

            "t2": data.get("t2"),

            "t3": data.get("t3"),

            "maxTemp": max_temp,

            "avgTemp": (
                round(avg_temp, 2)
                if avg_temp is not None
                else None
            ),


            # ----------------------------------------------
            # Humidity
            # ----------------------------------------------

            "h1": data.get("h1"),

            "h2": data.get("h2"),

            "h3": data.get("h3"),


            # ----------------------------------------------
            # Gas Sensors
            # ----------------------------------------------

            "mq2": mq2,

            "mq4": mq4,


            # ----------------------------------------------
            # Fault States
            # ----------------------------------------------

            "tempFault": temp_fault,

            "gasFault": gas_fault,


            # ----------------------------------------------
            # ACTUAL HARDWARE STATES FROM ESP32
            # ----------------------------------------------

            "fan": fan_state,

            "bulbs": bulb_state,

            "led": led_state,


            # ----------------------------------------------
            # Thresholds
            # ----------------------------------------------

            "tempThreshold": TEMP_THRESHOLD,

            "mq2Threshold": MQ2_THRESHOLD,

            "mq4Threshold": MQ4_THRESHOLD,


            # ----------------------------------------------
            # Sensor Health
            # ----------------------------------------------

            "sensorErrors": sensor_errors,

            "sensorDataValid": (
                any_temp_valid
            )
        }


        # ====================================================
        # CONVERT TO JSON
        # ====================================================

        processed_json = json.dumps(
            processed_payload
        )


        # ====================================================
        # PUBLISH PROCESSED DATA
        # ====================================================

        result = client.publish(
            PROCESSED_TOPIC,
            processed_json
        )


        # ====================================================
        # LOG PROCESSED DATA
        # ====================================================

        logger.info("")
        logger.info(
            "[MQTT PROCESSED PUBLISHED]"
        )

        logger.info(
            f"Topic   : {PROCESSED_TOPIC}"
        )

        logger.info(
            f"Payload : {processed_json}"
        )


        # Check publish result

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            logger.info(
                "Publish status: SUCCESS"
            )

        else:

            logger.error(
                f"Publish status: FAILED "
                f"(code {result.rc})"
            )


        logger.info(
            "=========================================="
        )


    # ========================================================
    # INVALID JSON ERROR
    # ========================================================

    except json.JSONDecodeError as e:

        logger.error(
            f"Invalid JSON received: {e}"
        )


    # ========================================================
    # OTHER ERRORS
    # ========================================================

    except Exception as e:

        logger.exception(
            f"Error processing MQTT message: {e}"
        )


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():

    logger.info("")
    logger.info(
        "=========================================="
    )

    logger.info(
        "Starting SmartGuard Edge Diagnostics Processor"
    )

    logger.info(
        f"MQTT Broker      : {MQTT_BROKER}:{MQTT_PORT}"
    )

    logger.info(
        f"Raw Topic        : {RAW_TOPIC}"
    )

    logger.info(
        f"Processed Topic  : {PROCESSED_TOPIC}"
    )

    logger.info(
        "=========================================="
    )


    # ========================================================
    # CREATE MQTT CLIENT
    # ========================================================

    try:

        # paho-mqtt 2.x

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="SmartGuardDiagnosticListener"
        )


    except (AttributeError, TypeError):

        # paho-mqtt 1.x

        client = mqtt.Client(
            client_id="SmartGuardDiagnosticListener"
        )


    # ========================================================
    # ASSIGN CALLBACKS
    # ========================================================

    client.on_connect = on_connect

    client.on_message = on_message

    client.on_disconnect = on_disconnect


    # ========================================================
    # CONNECT TO MQTT BROKER
    # ========================================================

    try:

        logger.info(
            "Connecting to local MQTT broker..."
        )


        client.connect(
            MQTT_BROKER,
            MQTT_PORT,
            keepalive=60
        )


    except Exception as e:

        logger.error(
            f"Cannot connect to MQTT broker: {e}"
        )

        logger.error(
            "Check that Mosquitto is running."
        )

        sys.exit(1)


    # ========================================================
    # RUN MQTT LOOP
    # ========================================================

    try:

        logger.info(
            "Waiting for ESP32 sensor data..."
        )


        client.loop_forever()


    except KeyboardInterrupt:

        logger.info(
            "Stopping SmartGuard listener..."
        )


    finally:

        try:
            client.disconnect()
        except Exception:
            pass


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":

    main()