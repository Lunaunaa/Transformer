import asyncio
import logging
import sys

import paho.mqtt.client as mqtt
import websockets


# ============================================================
# CONFIGURATION
# ============================================================

# Mosquitto runs on the SAME Raspberry Pi as this script.
# Therefore localhost is CORRECT.

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# listener.py publishes processed data to this topic

MQTT_TOPIC = "smartguard/processed"


# WebSocket server configuration

# 0.0.0.0 means:
# Accept WebSocket connections from other devices
# on the same network, including your laptop.

WS_HOST = "0.0.0.0"
WS_PORT = 6789


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("SmartGuardBridge")


# ============================================================
# SHARED STATE
# ============================================================

# All currently connected website clients

connected_clients = set()


# Store latest processed MQTT message.
# When a new website connects, it immediately receives
# the latest available sensor state.

latest_data = None


# Reference to the asyncio event loop

asyncio_loop = None


# ============================================================
# MQTT CONNECT CALLBACK
# ============================================================

def on_connect(client, userdata, flags, rc, *args):

    # Support both paho-mqtt v1.x and v2.x

    if isinstance(rc, int):
        connection_rc = rc

    elif hasattr(rc, "value"):
        connection_rc = rc.value

    else:
        connection_rc = (
            0 if str(rc) == "Success" else -1
        )


    if connection_rc == 0:

        logger.info(
            "=========================================="
        )

        logger.info(
            "Connected successfully to MQTT broker."
        )

        logger.info(
            f"Broker: {MQTT_BROKER}:{MQTT_PORT}"
        )


        # Subscribe to processed data from listener.py

        result, mid = client.subscribe(
            MQTT_TOPIC
        )


        if result == mqtt.MQTT_ERR_SUCCESS:

            logger.info(
                f"Subscribed to topic: {MQTT_TOPIC}"
            )

        else:

            logger.error(
                f"Failed to subscribe to: {MQTT_TOPIC}"
            )


        logger.info(
            "=========================================="
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
        "Disconnected from MQTT broker."
    )


# ============================================================
# MQTT MESSAGE CALLBACK
# ============================================================

def on_message(client, userdata, msg):

    global latest_data
    global asyncio_loop


    try:

        # Decode MQTT payload

        payload_str = msg.payload.decode(
            "utf-8"
        )


        # Store latest message

        latest_data = payload_str


        # Debug output

        logger.info("")
        logger.info(
            "=========================================="
        )

        logger.info(
            "[MQTT PROCESSED RECEIVED]"
        )

        logger.info(
            f"Topic   : {msg.topic}"
        )

        logger.info(
            f"Payload : {payload_str}"
        )


        # ====================================================
        # SEND TO WEBSITE CLIENTS
        # ====================================================

        if connected_clients and asyncio_loop:

            logger.info(
                f"Broadcasting to "
                f"{len(connected_clients)} "
                f"WebSocket client(s)..."
            )


            future = asyncio.run_coroutine_threadsafe(
                broadcast(payload_str),
                asyncio_loop
            )


            # Log exceptions if the asynchronous broadcast fails

            def broadcast_done(f):

                try:
                    f.result()

                except Exception as e:

                    logger.error(
                        f"Broadcast failed: {e}"
                    )


            future.add_done_callback(
                broadcast_done
            )


        else:

            logger.info(
                "No WebSocket clients currently connected."
            )


        logger.info(
            "=========================================="
        )


    except UnicodeDecodeError as e:

        logger.error(
            f"Could not decode MQTT payload: {e}"
        )


    except Exception as e:

        logger.exception(
            f"Error handling MQTT message: {e}"
        )


# ============================================================
# REGISTER WEBSOCKET CLIENT
# ============================================================

async def register(websocket):

    connected_clients.add(
        websocket
    )


    logger.info("")
    logger.info(
        "[WEBSOCKET CLIENT CONNECTED]"
    )

    logger.info(
        f"Client: {websocket.remote_address}"
    )

    logger.info(
        f"Total clients: {len(connected_clients)}"
    )


    # Immediately send latest known sensor data
    # to newly connected website.

    if latest_data is not None:

        try:

            await websocket.send(
                latest_data
            )


            logger.info(
                "[CACHED DATA SENT TO NEW CLIENT]"
            )


        except Exception as e:

            logger.error(
                f"Error sending cached data: {e}"
            )


# ============================================================
# UNREGISTER WEBSOCKET CLIENT
# ============================================================

async def unregister(websocket):

    if websocket in connected_clients:

        connected_clients.remove(
            websocket
        )


        logger.info("")
        logger.info(
            "[WEBSOCKET CLIENT DISCONNECTED]"
        )

        logger.info(
            f"Client: {websocket.remote_address}"
        )

        logger.info(
            f"Total clients: {len(connected_clients)}"
        )


# ============================================================
# WEBSOCKET CONNECTION HANDLER
# ============================================================

async def ws_handler(websocket, path=None):

    await register(
        websocket
    )


    try:

        # Keep connection alive.
        # The website does not need to send messages.

        async for message in websocket:

            # Ignore incoming messages from browser

            pass


    except websockets.ConnectionClosed:

        pass


    except Exception as e:

        logger.error(
            f"WebSocket client error: {e}"
        )


    finally:

        await unregister(
            websocket
        )


# ============================================================
# BROADCAST MQTT DATA TO ALL WEBSITE CLIENTS
# ============================================================

async def broadcast(message):

    if not connected_clients:

        return


    disconnected_clients = set()


    for client in list(
        connected_clients
    ):

        try:

            await client.send(
                message
            )


        except Exception as e:

            logger.warning(
                f"Could not send to "
                f"{client.remote_address}: {e}"
            )

            disconnected_clients.add(
                client
            )


    # Remove disconnected clients

    for client in disconnected_clients:

        await unregister(
            client
        )


    logger.info(
        "[WEBSOCKET BROADCAST COMPLETE]"
    )


# ============================================================
# START WEBSOCKET SERVER
# ============================================================

async def main_async():

    global asyncio_loop


    # Save current asyncio loop so MQTT callback
    # can safely schedule WebSocket broadcasts.

    asyncio_loop = asyncio.get_running_loop()


    logger.info(
        f"Starting WebSocket server "
        f"on {WS_HOST}:{WS_PORT}..."
    )


    async with websockets.serve(
        ws_handler,
        WS_HOST,
        WS_PORT
    ):

        logger.info(
            "=========================================="
        )

        logger.info(
            "WebSocket server started successfully."
        )

        logger.info(
            f"Listening on port: {WS_PORT}"
        )

        logger.info(
            "Website should connect using:"
        )

        logger.info(
            f"ws://<RASPBERRY_PI_IP>:{WS_PORT}"
        )

        logger.info(
            "=========================================="
        )


        # Run forever

        await asyncio.Future()


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info("")
    logger.info(
        "=========================================="
    )

    logger.info(
        "Starting SmartGuard MQTT-to-WebSocket Bridge"
    )

    logger.info(
        f"MQTT Broker : {MQTT_BROKER}:{MQTT_PORT}"
    )

    logger.info(
        f"MQTT Topic  : {MQTT_TOPIC}"
    )

    logger.info(
        f"WS Port     : {WS_PORT}"
    )

    logger.info(
        "=========================================="
    )


    # ========================================================
    # CREATE MQTT CLIENT
    # ========================================================

    try:

        # paho-mqtt 2.x

        mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="SmartGuardWSBridge"
        )


    except (AttributeError, TypeError):

        # paho-mqtt 1.x

        mqtt_client = mqtt.Client(
            client_id="SmartGuardWSBridge"
        )


    # ========================================================
    # ASSIGN MQTT CALLBACKS
    # ========================================================

    mqtt_client.on_connect = on_connect

    mqtt_client.on_message = on_message

    mqtt_client.on_disconnect = on_disconnect


    # ========================================================
    # CONNECT TO MOSQUITTO
    # ========================================================

    try:

        logger.info(
            "Connecting to local MQTT broker..."
        )


        mqtt_client.connect(
            MQTT_BROKER,
            MQTT_PORT,
            keepalive=60
        )


    except Exception as e:

        logger.error(
            f"Failed to connect to MQTT broker: {e}"
        )

        logger.error(
            "Check that Mosquitto is running."
        )

        sys.exit(1)


    # Run MQTT network loop in background thread

    mqtt_client.loop_start()


    # ========================================================
    # RUN WEBSOCKET SERVER
    # ========================================================

    try:

        asyncio.run(
            main_async()
        )


    except KeyboardInterrupt:

        logger.info(
            "Stopping SmartGuard WebSocket bridge..."
        )


    finally:

        mqtt_client.loop_stop()

        mqtt_client.disconnect()


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":

    main()