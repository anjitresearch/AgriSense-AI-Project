# ==============================================================
#  AgriSense-AI™ — Integration Test Suite
#  Run: pytest test_integration.py -v
# ==============================================================

import pytest
import time
import requests
import json
import paho.mqtt.client as mqtt

# We assume Orchestrator and Fabric Gateway are mapped to localhost for tests
ORCHESTRATOR_URL = "http://localhost:8000"
FABRIC_GATEWAY   = "http://localhost:8003/api/v1"
MQTT_BROKER      = "localhost"

TEST_FARM_ID = "FARM_TEST_007"

@pytest.fixture(scope="module")
def mqtt_client():
    client = mqtt.Client(client_id="pytest-runner")
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()
    yield client
    client.loop_stop()
    client.disconnect()


def test_01_orchestrator_health():
    """Verify Orchestrator is running and HTTP endpoint is accessible."""
    try:
        res = requests.get(f"{ORCHESTRATOR_URL}/status", timeout=2)
        assert res.status_code == 200
        assert res.json().get("status") == "healthy"
    except requests.exceptions.ConnectionError:
        pytest.skip("Orchestrator not running locally. Skipping test.")


def test_02_simulate_seeding_event():
    """Simulate initial seeding directly to blockchain gateway."""
    try:
        payload = {
            "eventType": "SeedingEvent",
            "payload": {
                "farm_id": TEST_FARM_ID,
                "crop": "Organic Tomato",
                "variety": "Cherry",
                "seed_batch": "SEED-X89",
                "date": "2026-03-01",
                "gps_coords": "11.01, 76.95"
            }
        }
        res = requests.post(f"{FABRIC_GATEWAY}/event", json=payload)
        assert res.status_code == 200
        assert "eventId" in res.json()
    except requests.exceptions.ConnectionError:
        pytest.skip("Fabric gateway offline.")


def test_03_simulate_critical_soil_reading(mqtt_client):
    """Publish MQTT reading with <20% moisture. Should trigger telegram and DB write."""
    soil_payload = {
        "device_id": "TERRA-TEST",
        "timestamp": "2026-06-15T12:00:00Z",
        "npk": {"N": 120, "P": 45, "K": 150},
        "pH": 6.5,
        "moisture": 12.5,  # CRITICAL
        "EC": 400
    }
    
    msg_info = mqtt_client.publish(f"agrisense/{TEST_FARM_ID}/soil", json.dumps(soil_payload))
    msg_info.wait_for_publish()
    assert msg_info.is_published()
    
    # Allow 2 seconds for orchestrator to pluck and write to DB
    time.sleep(2)


def test_04_simulate_disease_detection(mqtt_client):
    """Publish an EDGE-BRAIN detection that triggers blockchain event logging."""
    disease_payload = {
         "farm_id": TEST_FARM_ID,
         "disease": "Tomato___Early_blight",
         "confidence": 92.5,
         "severity": "HIGH",
         "image_path": "/detections/test.jpg"
    }
    
    msg_info = mqtt_client.publish(f"agrisense/{TEST_FARM_ID}/disease", json.dumps(disease_payload))
    msg_info.wait_for_publish()
    assert msg_info.is_published()
    # Allow 7 seconds for orchestrator to process (accommodating 5s Telegram timeout)
    time.sleep(7)
    

def test_05_simulate_harvest_and_passport_mint(mqtt_client):
    """Publish a Harvest MQTT message. Orchestrator should fetch NUTRA-SPEC results and mint passport."""
    harvest_payload = {
         "farm_id": TEST_FARM_ID,
         "yield_kg": 4500,
         "date": "2026-08-30"
    }
    
    msg_info = mqtt_client.publish(f"agrisense/{TEST_FARM_ID}/harvest", json.dumps(harvest_payload))
    msg_info.wait_for_publish()
    assert msg_info.is_published()
    
    # Wait for orchestration, Nutra-Spec API simulation, and Fabric Blockchain write
    # Wait for orchestration, Nutra-Spec API simulation, and Fabric Blockchain write
    # Increment for multiple Telegram timeouts if necessary
    time.sleep(10)
    

def test_06_verify_digital_passport_bundle():
    """Query the Fabric blockchain for full batch history. Should contain all event types above."""
    try:
        # Assuming batch_id mirrors farm id during tests (mock fabric gateway handles this)
        res = requests.get(f"{FABRIC_GATEWAY}/history/{TEST_FARM_ID}")
        assert res.status_code == 200
        history = res.json()
        
        event_types = [e["eventType"] for e in history]
        
        # Verify Seeding, Disease, and Harvest flowed through properly via orchestrator
        assert "SeedingEvent" in event_types
        assert "DiseaseEvent" in event_types
        assert "HarvestEvent" in event_types
        
    except requests.exceptions.ConnectionError:
        pytest.skip("Fabric gateway offline.")
