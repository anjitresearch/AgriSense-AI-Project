"""
==============================================================
 EDGE-BRAIN™ — edge_brain_api.py
 FastAPI Interface for Two-Stage TinyML Pipeline
 
 Endpoints:
 - POST /predict: Processes uploaded image
 - GET /latest: Gets most recent detection from SQLite
 - GET /history: Gets N recent detections from SQLite
 - WS /ws/live: Streams detections in real-time
==============================================================
"""

import os
import sqlite3
import cv2
import numpy as np
import asyncio
import json
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from edge_brain_inference import EdgeBrainEngine, init_db, DB_PATH

app = FastAPI(title="EDGE-BRAIN API", description="Two-Stage TinyML Inference Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# STATE & INIT
# ──────────────────────────────────────────────
engine: EdgeBrainEngine = None
active_connections: List[WebSocket] = []

@app.on_event("startup")
async def startup_event():
    global engine
    init_db()
    # Try loading engine, fail gracefully if models missing
    try:
        engine = EdgeBrainEngine()
    except Exception as e:
        print(f"Warning: Engine failed to start ({e}). API running in degraded mode.")

# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────
class Detection(BaseModel):
    timestamp: str
    crop: str
    disease: str
    confidence: float
    action: str
    stage1_ms: float
    stage2_ms: float
    is_diseased: Optional[bool] = None

# ──────────────────────────────────────────────
# REST ENDPOINTS
# ──────────────────────────────────────────────
@app.post("/predict", response_model=Detection)
async def predict_image(file: UploadFile = File(...)):
    if not engine:
        return {"error": "Models not loaded. Train models first."}
        
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Run full two-stage pipeline
    res = engine.predict(frame, save_path="")
    
    # Broadcast to websocket clients
    await broadcast_detection(res)
    
    return Detection(
        timestamp=res["timestamp"],
        crop=res["crop"],
        disease=res["disease"],
        confidence=res["confidence"],
        action=res["action"],
        stage1_ms=res.get("stage1_inference_ms", 0),
        stage2_ms=res.get("stage2_inference_ms", 0),
        is_diseased=res.get("is_diseased", False)
    )

@app.get("/")
def read_root():
    return {"status": "EDGE-BRAIN Online", "engine_ready": engine is not None}

@app.get("/latest")
def get_latest():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT timestamp, crop, disease, confidence, action, stage1_ms, stage2_ms FROM detections ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    
    if not row:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "crop": "None", "disease": "Waiting for data...", 
            "confidence": 0.0, "action": "Please run a detection.",
            "stage1_ms": 0.0, "stage2_ms": 0.0, "is_diseased": False
        }
        
    return Detection(
        timestamp=row[0], crop=row[1], disease=row[2],
        confidence=row[3], action=row[4], 
        stage1_ms=row[5] or 0.0, stage2_ms=row[6] or 0.0,
        is_diseased=(row[2] != "HEALTHY")
    )

@app.get("/history", response_model=List[Detection])
def get_history(limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT timestamp, crop, disease, confidence, action, stage1_ms, stage2_ms FROM detections ORDER BY id DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append(Detection(
            timestamp=row[0], crop=row[1], disease=row[2],
            confidence=row[3], action=row[4], 
            stage1_ms=row[5] or 0.0, stage2_ms=row[6] or 0.0,
            is_diseased=(row[2] != "HEALTHY")
        ))
    return results

# ──────────────────────────────────────────────
# WEBSOCKET (REAL-TIME STREAM)
# ──────────────────────────────────────────────
async def broadcast_detection(data: dict):
    for conn in active_connections:
        try:
            await conn.send_text(json.dumps(data))
        except:
            active_connections.remove(conn)

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Keeps connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
