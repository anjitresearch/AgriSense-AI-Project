# AgriSense-AI™ — Master Monorepo

> **The ultimate edge-to-consumer precision agriculture platform.**  
> Integrating embedded IoT, TinyML computer vision, hyperspectral spectroscopy, event-driven orchestration, and immutable blockchain traceability.

---

## 🏗 System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        AGRISENSE-AI™ PLATFORM                          │
│                                                                        │
│  [TERRA-NODE™]        [SKYWATCH-H™]         [NUTRA-SPEC™]              │
│  Sensors / ESP32      Drones / API          IR Spectroscopy / PLSR     │
│       │                    │                       │                   │
│       ├── MQTT (1883) ─────┴─► [EDGE-BRAIN™] ◄─────┘                   │
│       │                        Raspberry Pi 4                          │
│       │                                                                │
│       └───────────► [ ORCHESTRATOR SERVICE ]                           │
│                     Python / MQTT Sub                                  │
│                              │                                         │
│                ┌─────────────┼──────────────┐                          │
│                ▼             ▼              ▼                          │
│           [InfluxDB]    [PostgreSQL]    [CHAIN-PROOF™]                 │
│           Soil Data     Meta / Alerts   Hyperledger Fabric             │
│                │             │              │                          │
│                └──────► [ REACT DASHBOARD ] ◄──────┘                   │
│                            WebSocket / API                             │
│                                                                        │
│                      [ TELEGRAM ALERT BOT ]                            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Prerequisites

**Software:**
- Docker Desktop / Engine (v24+)
- Docker Compose (v2+)
- Python 3.10+ (for local scripts/tests)
- Node.js 18+ (for UI dev)

**Hardware:**
- ESP32-S3 DevKitC-1 with RS485 converter max485
- Capacitive Moisture, pH (Analog), DS18B20 Temp
- Raspberry Pi 4 (8GB) + Arducam 

---

## 🚀 Quick Start (5 Commands)

Deploy the entire microservice ecosystem locally using Docker Compose:

1. **Clone & setup environment:**
   ```bash
   git clone https://github.com/your-org/agrisense-ai.git
   cd agrisense-ai
   cp .env.example .env
   # Edit .env to add your INFLUX_TOKEN and TELEGRAM credentials
   ```

2. **Boot the Fabric Blockchain (CHAIN-PROOF™):**
   ```bash
   cd chain_proof
   ./network-setup.sh
   cd ..
   ```

3. **Start Core Infrastructure (DBs, MQTT, Orchestrator, Nginx):**
   ```bash
   docker-compose up -d
   ```

4. **Run Database Migrations (Auto-created by Orchestrator on boot):**
   ```bash
   docker logs agrisense-orchestrator  # Verify "PostgreSQL initialised"
   ```

5. **Start Simulated Farm Traffic:**
   ```bash
   python terra_node/simulate_terra_node.py
   ```

**Access Points:**
- **Dashboard:** `http://localhost:80` (Proxied via NGINX)
- **MQTT WS:** `ws://localhost:9001`
- **InfluxDB:** `http://localhost:8086`

---

## 🔧 Hardware Wiring Guide (TERRA-NODE™)

Here is exactly how the ESP32-S3 is wired on the edge:

```text
      [ ESP32-S3 DevKit ]
         3V3 ──► Power bus
         GND ──► Ground bus
         IO2 ──► Status LED (Blinks on MQTT publish)
         IO4 ──► DS18B20 Data Line (uses 4.7kΩ pull-up to 3V3)

   [ Analog Sensors ]
        IO34 ──► Capacitive Moisture (AOUT)
        IO35 ──► pH Module (pOUT)
        IO32 ──► EC Module (AOUT)

   [ MAX485 RS485 Module ] ──► (To NPK Sensor A/B Lines)
        IO16 (RX) ──► RO
        IO17 (TX) ──► DI
        IO18 (DE) ──► DE + RE (tied together to control read/write direction)
```

---

## 📡 API Reference Matrix

All APIs are routed cleanly through the NGINX reverse proxy (`http://localhost:80`):

| Method | NGINX Route | Target Service | Function |
|--------|-------------|----------------|----------|
| `POST` | `/api/soil/*` | Orchestrator/MQTT | Ingests sensor data (Internal) |
| `POST` | `/api/detect` | `edge-brain:8001/predict` | Two-stage INT8 offline inference |
| `GET`  | `/api/detect/history` | `edge-brain:8001/history` | Fetches SQLite local offline logs |
| `POST` | `/api/nutra` | `nutra-spec:8002/predict/nutra`| PLSR Chemical Prediction (Harvest) |
| `POST` | `/api/chain/event` | `chain-proof:8003/api/v1/event`| Record to Hyperledger Fabric |
| `GET`  | `/api/chain/passport/{id}`| `chain-proof:8003/api/v1/passport/{id}`| Generate Digital Passport + QR Seal |

---

## 🛠 Troubleshooting (Top Issues)

1. **`ModuleNotFoundError: No module named 'tensorflow'`**
   Using an x86/Windows machine instead of Pi. In `edge_brain/requirements.txt`, comment out `tflite-runtime` and uncomment `tensorflow`.

2. **Dashboard WebSocket fails (Red "ERROR" badge)**
   Ensure Mosquitto container mapped port `9001` externally and the browser allows local untrusted SSL if forced. Try navigating to `http://localhost:9001` to accept the cert warning if applicable.

3. **Orchestrator exits with `psycopg2.OperationalError`**
   The `postgres` container didn't boot fast enough. Wait 5 seconds and restart orchestrator: `docker restart agrisense-orchestrator`.

4. **Nginx 502 Bad Gateway `/api/chain`**
   The CHAIN-PROOF FastAPI container failed. Ensure the Fabric network (`network-setup.sh`) is running _before_ docker-compose, as the API needs the `fabric` shared volume to map certificates.

---
© 2026 AgriSense-AI™ Monorepo
