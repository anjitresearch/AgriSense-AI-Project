# ==============================================================
#  TERRA-NODE™ — Python MQTT Simulator
#  Simulates fake soil sensor data over MQTT every 5 seconds.
#  Usage: python simulate_terra_node.py
# ==============================================================

import time
import json
import random
import paho.mqtt.client as mqtt
from datetime import datetime, timezone

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
FARM_ID = "farm001"
DEVICE_ID = "TERRA-SIM-01"
TOPIC = f"agrisense/{FARM_ID}/soil"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"Failed to connect, return code {rc}")

client = mqtt.Client(client_id=DEVICE_ID)
client.on_connect = on_connect

# Try to connect, fallback gracefully if broker is missing
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
except Exception as e:
    print(f"Warning: Could not connect to MQTT broker ({e}). Ensure Mosquitto is running.")
    print("Simulator will run in standalone mode printing to console...")

client.loop_start()

print(f"TERRA-NODE Simulator starting... Publishing to {TOPIC} every 5 seconds.")
print("Press Ctrl+C to stop.")

try:
    # Initial realistic values
    npk_n = 120
    npk_p = 45
    npk_k = 180
    ph = 6.5
    ec = 420
    moisture = 40.0
    temp = 22.5
    batt = 100.0

    while True:
        # Simulate slight random walks
        npk_n = max(10, min(300, npk_n + random.randint(-5, 5)))
        npk_p = max(5, min(100, npk_p + random.randint(-2, 2)))
        npk_k = max(20, min(400, npk_k + random.randint(-8, 8)))
        
        ph = round(max(0.0, min(14.0, ph + random.uniform(-0.1, 0.1))), 2)
        ec = round(max(0, ec + random.randint(-15, 15)), 2)
        moisture = round(max(0.0, min(100.0, moisture + random.uniform(-1.0, 1.0))), 1)
        temp = round(max(-10.0, min(60.0, temp + random.uniform(-0.3, 0.3))), 1)
        batt = round(max(0.0, batt - random.uniform(0.0, 0.05)), 1)
        
        payload = {
            "device_id": DEVICE_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "npk": {
                "N": npk_n,
                "P": npk_p,
                "K": npk_k
            },
            "pH": ph,
            "EC": ec,
            "moisture": moisture,
            "temperature": temp,
            "battery_pct": batt
        }

        json_payload = json.dumps(payload)
        
        try:
            client.publish(TOPIC, json_payload)
            print(f"[SIMULATOR] Published -> {json_payload}")
        except Exception:
            print(f"[SIMULATOR - No Broker] {json_payload}")
            
        time.sleep(5)
        
except KeyboardInterrupt:
    print("\nStopping simulator...")
finally:
    client.loop_stop()
    client.disconnect()
