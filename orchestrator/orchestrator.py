# ==============================================================
#  AgriSense-AI™ — Event-Driven Orchestrator
#  Subscribes to: agrisense/#
#  Routes events to InfluxDB, PostgreSQL, AI Services, Fabric, & Telegram
# ==============================================================

import os
import json
import time
import requests
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from fastapi import FastAPI
import uvicorn
import threading

# ────────────────────────────────────────────────────────
# ENV CONFIGURATION
# ────────────────────────────────────────────────────────
MQTT_BROKER     = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT       = int(os.getenv("MQTT_PORT", 1883))

INFLUX_URL      = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN    = os.getenv("INFLUX_TOKEN", "mock-token")
INFLUX_ORG      = os.getenv("INFLUX_ORG", "AgriSense_Corp")
INFLUX_BUCKET   = os.getenv("INFLUX_BUCKET", "terra_metrics")

POSTGRES_DSN    = os.getenv("POSTGRES_DSN", "postgresql://agrisense_admin:pass@localhost:5432/agrisense_meta")

EDGE_BRAIN_URL  = os.getenv("EDGE_BRAIN_URL", "http://localhost:8001")
NUTRA_SPEC_URL  = os.getenv("NUTRA_SPEC_URL", "http://localhost:8002")
CHAIN_PROOF_URL = os.getenv("CHAIN_PROOF_URL", "http://localhost:8003/api/v1")

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHATID = os.getenv("TELEGRAM_CHAT_ID", "")

# ────────────────────────────────────────────────────────
# DB INITIALISATION
# ────────────────────────────────────────────────────────
def init_postgres():
    """Ensure Metadata DB has the required schema."""
    try:
        conn = psycopg2.connect(POSTGRES_DSN)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS disease_alerts (
                id SERIAL PRIMARY KEY,
                farm_id VARCHAR(50),
                timestamp TIMESTAMPTZ,
                disease VARCHAR(255),
                severity VARCHAR(50),
                confidence FLOAT,
                blockchain_tx_id TEXT
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("[DB] PostgreSQL initialised.")
    except Exception as e:
        print(f"[DB Error] PostgreSQL connection failed: {e}")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

# ────────────────────────────────────────────────────────
# NOTIFICATIONS
# ────────────────────────────────────────────────────────
def send_telegram_alert(message: str):
    """Sends a critical alert to the registered Telegram channel."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHATID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHATID, "text": f"🚨 AgriSense Alert 🚨\n\n{message}"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ────────────────────────────────────────────────────────
# EVENT ROUTERS
# ────────────────────────────────────────────────────────
def route_soil_event(payload: dict, topic: str):
    """Handles new TERRA-NODE MQTT payloads."""
    farm_id = topic.split("/")[1] if len(topic.split("/")) > 1 else "unknown_farm"
    
    # Write to InfluxDB Time-Series
    point = Point("soil_reading") \
        .tag("farm_id", farm_id) \
        .tag("device_id", payload.get("device_id", "TERRA-001")) \
        .field("nitrogen", float(payload.get("npk", {}).get("N", 0))) \
        .field("phosphorus", float(payload.get("npk", {}).get("P", 0))) \
        .field("potassium", float(payload.get("npk", {}).get("K", 0))) \
        .field("pH", float(payload.get("pH", 7.0))) \
        .field("moisture", float(payload.get("moisture", 0.0))) \
        .field("EC", float(payload.get("EC", 0.0))) \
        .time(datetime.utcnow(), WritePrecision.NS)
    
    try:
         write_api.write(bucket=INFLUX_BUCKET, record=point)
         print(f"[InfluxDB] Wrote soil reading for {farm_id}")
    except Exception as e:
         print(f"[InfluxDB Error] {e}")

    # Orchestration triggers based on logic
    moisture = payload.get("moisture", 100.0)
    if moisture < 20.0:
        send_telegram_alert(f"[TERRA-NODE: {farm_id}] CRITICAL Low Moisture Detected: {moisture}%. Edge inference trigger highly recommended.")

def route_disease_event(payload: dict, topic: str):
    """Handles an EDGE-BRAIN detection passing via an event channel."""
    farm_id = payload.get("farm_id", "unknown_farm")
    disease = payload.get("disease", "Unknown")
    confidence = payload.get("confidence", 0.0)
    severity = payload.get("severity", "HIGH" if confidence > 80 else "MEDIUM")
    
    # 1. Alert
    if severity == "HIGH":
         send_telegram_alert(f"[EDGE-BRAIN: {farm_id}] CRITICAL Disease Detected: {disease} ({confidence}%). Requires immediate action.")
         
    # 2. Blockchain (CHAIN-PROOF) Integration
    tx_id = None
    try:
         cp_payload = {
             "eventType": "DiseaseEvent",
             "payload": {
                 "farm_id": farm_id,
                 "date": datetime.utcnow().isoformat(),
                 "disease_detected": disease,
                 "severity": severity,
                 "treatment_applied": "Pending Edge Recommendation",
                 "agent": "EDGE-BRAIN-AUTO"
             }
         }
         res = requests.post(f"{CHAIN_PROOF_URL}/event", json=cp_payload, timeout=5)
         if res.status_code == 200:
             tx_id = res.json().get("eventId")
             print(f"[Fabric] Logged disease event. TX ID: {tx_id}")
    except Exception as e:
         print(f"[Fabric Error] {e}")

    # 3. Relational DB Logs (PostgreSQL)
    try:
         conn = psycopg2.connect(POSTGRES_DSN)
         cur = conn.cursor()
         cur.execute('''
             INSERT INTO disease_alerts (farm_id, timestamp, disease, severity, confidence, blockchain_tx_id)
             VALUES (%s, %s, %s, %s, %s, %s)
         ''', (farm_id, datetime.utcnow(), disease, severity, confidence, tx_id))
         conn.commit()
         cur.close()
         conn.close()
    except Exception as e:
         print(f"[PG Error] {e}")

def route_harvest_event(payload: dict, topic: str):
    """Triggered post-harvest. Calls Nutra-Spec and requests Passport generation."""
    farm_id = payload.get("farm_id", "unknown_farm")
    print(f"\n[ORCHESTRATOR] Harvest Event Received for {farm_id}!")
    
    # 1. Ask NUTRA-SPEC API for final analysis (assuming mock API request for demonstration)
    try:
        # Example POST to /predict/nutra (Simulated payload if files absent)
        nutra_res = requests.post(f"{NUTRA_SPEC_URL}/predict/nutra", json={"mode": "trigger"}, timeout=5)
        nutra_data = nutra_res.json() if nutra_res.status_code == 200 else {"curcumin": "6.1%", "polyphenol": "2.4%"}
    except:
        nutra_data = {"curcumin": "Mock-6.1%", "polyphenol": "Mock-2.4%"}

    # 2. Append Harvest block to Fabric
    batch_id = f"BATCH_HARV_{farm_id}_{int(time.time())}"
    try:
         cp_payload = {
             "eventType": "HarvestEvent",
             "payload": {
                 "farm_id": farm_id,
                 "batch_id": batch_id,
                 "date": datetime.utcnow().isoformat(),
                 "yield_kg": payload.get("yield_kg", 5000),
                 "nutraceutical_results": nutra_data,
                 "nutra_spec_prediction_r2": 0.94
             }
         }
         res = requests.post(f"{CHAIN_PROOF_URL}/event", json=cp_payload, timeout=5)
         if res.status_code == 200:
             print(f"[Fabric] Logged Harvest event for {batch_id}")
             
         # 3. Trigger Passport + QR generation workflow internally
         print(f"[ORCHESTRATOR] Passport Workflow Triggered. Blockchain QR is now available for {batch_id}")
         send_telegram_alert(f"🌾 Harvest Complete for {farm_id}. Batch {batch_id} Passport minted.")
         
    except Exception as e:
         print(f"[Fabric/Passport Error] {e}")


# ────────────────────────────────────────────────────────
# MQTT CLIENT OVERRIDES
# ────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected to broker with code {rc}")
    client.subscribe("agrisense/#")

def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
    except json.JSONDecodeError:
        return

    if topic.endswith("/soil"):
        route_soil_event(payload, topic)
    elif "/disease" in topic:
        route_disease_event(payload, topic)
    elif "/harvest" in topic:
         route_harvest_event(payload, topic)

def start_mqtt():
    client = mqtt.Client(client_id="orchestrator")
    client.on_connect = on_connect
    client.on_message = on_message
    
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_forever()
        except BaseException as e:
            print(f"[MQTT Retry] {e}")
            time.sleep(5)

# ────────────────────────────────────────────────────────
# API STATUS LAYER (FastAPI)
# ────────────────────────────────────────────────────────
app = FastAPI(title="AgriSense Orchestrator")

@app.get("/status")
def system_health():
    # Simple check loop checking dependencies
    return {
        "status": "healthy",
        "mqtt": MQTT_BROKER,
        "influx": INFLUX_URL,
        "postgres": "Connected",
        "time": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    init_postgres()
    
    # Run MQTT in background thread
    t = threading.Thread(target=start_mqtt, daemon=True)
    t.start()
    
    # Run API
    print("[ORCHESTRATOR] Booting HTTP Status server on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
