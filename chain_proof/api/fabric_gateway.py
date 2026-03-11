# ==============================================================
#  CHAIN-PROOF™ — Fabric API Gateway
#  Platform: Python FastAPI
#  Purpose: REST wrapper for Hyperledger Fabric chaincode
# ==============================================================

import json
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any

# Mock Fabric SDK integration (since running true Fabric requires the full environment)
# In production, this would use `fabric-sdk-py` or `requests` to a Node.js Fabric REST server

app = FastAPI(title="CHAIN-PROOF™ Digital Passport Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# MOCK LEDGER STORAGE (For Demonstration)
# ──────────────────────────────────────────────
MOCK_LEDGER = []

# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────
class FarmEvent(BaseModel):
    eventType: str
    payload: Dict[str, Any]

# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

@app.post("/api/v1/event")
def record_event(event: FarmEvent):
    """Submits a single farm event to the blockchain."""
    try:
        # In production: Use Fabric SDK to submitTransaction('recordEvent', ...)
        payload_str = json.dumps(event.payload)
        
        # Determine ID based on event logic
        event_id = f"{event.eventType}_{event.payload.get('farm_id', 'unknown')}_{len(MOCK_LEDGER)}"
        
        # Idempotency check 
        if any(e['eventId'] == event_id for e in MOCK_LEDGER):
            raise HTTPException(status_code=409, detail="Duplicate Event Rejected")
            
        record = {
            "eventId": event_id,
            "eventType": event.eventType,
            "batchId": event.payload.get('batch_id', event.payload.get('farm_id', 'unknown')),
            "data": event.payload
        }
        MOCK_LEDGER.append(record)
        
        return {"success": True, "eventId": event_id, "message": "Transaction committed"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/history/{farm_id}")
def get_history(farm_id: str):
    """Retrieves full audit trail for a farm."""
    # In production: evaluateTransaction('getHistory', farm_id)
    history = [e for e in MOCK_LEDGER if e['data'].get('farm_id') == farm_id]
    return history

@app.get("/api/v1/passport/{batch_id}")
def generate_passport(batch_id: str):
    """Generates the comprehensive Digital Passport for a batch."""
    # In production: evaluateTransaction('generatePassport', batch_id)
    events = [e for e in MOCK_LEDGER if e['batchId'] == batch_id]
    
    if not events:
        # Provide sample data if empty for the sake of the QR generator demo
        events = [
            {"eventType": "SeedingEvent", "data": {"farm_id": "FARM-1", "crop": "Turmeric", "variety": "Pragati", "date": "2026-01-10"}},
            {"eventType": "SoilEvent", "data": {"farm_id": "FARM-1", "pH": 6.8, "moisture": 45, "lab_certified": True}},
            {"eventType": "HarvestEvent", "data": {"farm_id": "FARM-1", "date": "2026-10-15", "yield_kg": 5000, "nutraceutical_results": {"curcumin": 5.4, "polyphenol": 2.1}, "nutra_spec_prediction_r2": 0.94}}
        ]
        
    import hashlib
    timeline_str = json.dumps(events, sort_keys=True)
    batch_hash = hashlib.sha256(timeline_str.encode()).hexdigest()
    
    return {
        "batchId": batch_id,
        "passportHash": batch_hash,
        "timeline": events
    }

@app.get("/api/v1/verify/{batch_id}/{provided_hash}")
def verify_certificate(batch_id: str, provided_hash: str):
    """Verifies a consumer passport hash against the ledger."""
    # In production: evaluateTransaction('verifyCertificate', batch_id, hash)
    passport = generate_passport(batch_id)
    is_verified = (passport["passportHash"] == provided_hash)
    
    return {
        "verified": is_verified,
        "batchId": batch_id,
        "providedHash": provided_hash,
        "calculatedHash": passport["passportHash"],
        "certdetails": passport if is_verified else None
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
