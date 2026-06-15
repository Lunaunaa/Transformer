"""
SmartGuard - MQTT to WebSocket Bridge
--------------------------------------
Subscribes to MQTT topic: smartguard/processed
Broadcasts to all connected WebSocket clients on port 6789

Run:
    python3 bridge.py

Install:
    pip install websockets paho-mqtt
"""

import asyncio
import json
import threading
import websockets
import paho.mqtt.client as mqtt

# ─── Config ───────────────────────────────────────────────────────────────
MQTT_BROKER   = "localhost"
MQTT_PORT     = 1883
MQTT_TOPIC    = "smartguard/processed"
WS_HOST       = "0.0.0.0"   # accept connections from any device on network
WS_PORT       = 6789

# ─── Shared state ─────────────────────────────────────────────────────────
connected_clients = set()
latest_data       = None
loop              = None   # asyncio event loop reference

# ─── Broadcast to all WebSocket clients ───────────────────────────────────
def broadcast(data: str):
    if not connected_clients:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(data), loop)

async def _broadcast(data: str):
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send(data)
        except Exception:
            dead.add(ws)
    connected_clients.difference_update(dead)

# ─── MQTT Callbacks ───────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected, subscribing to {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"[MQTT] Failed rc={rc}")

def on_message(client, userdata, msg):
    global latest_data
    try:
        latest_data = msg.payload.decode()
        broadcast(latest_data)
    except Exception as e:
        print(f"[MQTT] Error: {e}")

# ─── WebSocket Handler ────────────────────────────────────────────────────
async def ws_handler(websocket, path):
    connected_clients.add(websocket)
    print(f"[WS] Client connected: {websocket.remote_address}")

    # Send latest data immediately on connect so dashboard isn't blank
    if latest_data:
        try:
            await websocket.send(latest_data)
        except Exception:
            pass

    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f"[WS] Client disconnected: {websocket.remote_address}")

# ─── Start MQTT in background thread ──────────────────────────────────────
def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_forever()

# ─── Main ─────────────────────────────────────────────────────────────────
async def main():
    global loop
    loop = asyncio.get_event_loop()

    # MQTT in background thread
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    print(f"[WS] WebSocket server started on ws://{WS_HOST}:{WS_PORT}")
    print(f"[WS] Open dashboard.html in your browser")
    print(f"[WS] Use your Pi's IP address in the dashboard")

    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        await asyncio.Future()   # run forever

if __name__ == "__main__":
    asyncio.run(main())