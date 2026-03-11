"""
==============================================================
 EDGE-BRAIN™ — edge_brain_inference.py
 Two-Stage Inference Engine for Raspberry Pi 4
 
 Features:
 - Camera capture loop (OpenCV) w/ Simulation mode
 - Stage 1: INT8 MobileNetV3 Screening (<50ms)
 - Stage 2: Transformer Classification (only if flagged)
 - Local SQLite Logging (detections.db)
 - Rich Terminal UI output
==============================================================
"""

import cv2
import numpy as np
import time
import os
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Use TFLite Runtime for Edge devices, fallback to TensorFlow
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    import tensorflow as tf
    tflite = tf.lite

from rich.console import Console
from rich.table import Table
from rich import box

# ──────────────────────────────────────────────
# CONFIG & CLASSES
# ──────────────────────────────────────────────
STAGE1_MODEL_PATH = "models/stage1_mobilenetv3_int8.tflite"
STAGE2_MODEL_PATH = "models/stage2_transformer.tflite"
DB_PATH = "detections.db"
TEST_IMG_DIR = "test_images"

STAGE1_THRESHOLD = 0.65  # Confidence > 0.65 -> Diseased

DISEASE_ACTIONS = {
    "Tomato___Bacterial_spot": "Apply copper-based bactericide. Avoid overhead watering.",
    "Tomato___Early_blight": "Apply chlorothalonil fungicide. Prune lower leaves.",
    "Tomato___Late_blight": "Immediate fungicidal spray (mancozeb). Destroy infected plants.",
    "Tomato___Leaf_Mold": "Increase spacing for airflow. Apply calcium spray.",
    "Tomato___Septoria_leaf_spot": "Remove diseased leaves. Apply chlorothalonil.",
    "Tomato___Spider_mites Two-spotted_spider_mite": "Apply neem oil or insecticidal soap.",
    "Tomato___Target_Spot": "Apply fungicide. Avoid working in wet fields.",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus": "Control whiteflies. Uproot infected plants.",
    "Tomato___Tomato_mosaic_virus": "No cure. Destroy plants. Disinfect tools.",
    "Rice___Brown_Spot": "Apply correct fertiliser balance (N/K). Use iprodione if severe.",
    "UNKNOWN": "Consult local agronomist."
}

DISEASE_CLASSES = list(DISEASE_ACTIONS.keys())[:-1] # Exclude UNKNOWN

console = Console()

# ──────────────────────────────────────────────
# DATABASE INIT
# ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            crop TEXT,
            disease TEXT,
            confidence REAL,
            action TEXT,
            image_path TEXT,
            stage1_ms REAL,
            stage2_ms REAL
        )
    ''')
    conn.commit()
    conn.close()

def log_detection(result: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO detections (timestamp, crop, disease, confidence, action, image_path, stage1_ms, stage2_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        result["timestamp"], result["crop"], result["disease"], 
        result["confidence"], result["action"], result.get("image_path", ""),
        result.get("stage1_inference_ms", 0), result.get("stage2_inference_ms", 0)
    ))
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# INFERENCE ENGINE
# ──────────────────────────────────────────────
class EdgeBrainEngine:
    def __init__(self):
        console.print("[dim]Initialising EDGE-BRAIN Engine...[/dim]")
        
        self.model_1_path = "models/stage1_mobilenetv3.h5"
        self.model_2_path = "models/stage2_transformer.h5"
        
        if not os.path.exists(self.model_1_path) or not os.path.exists(self.model_2_path):
            console.print(f"[bold red]Models not found! Run model_trainer.py first.[/bold red]")
            exit(1)

        import tensorflow as tf
        self.model_1 = tf.keras.models.load_model(self.model_1_path)
        self.model_2 = tf.keras.models.load_model(self.model_2_path)
        
        # Warmup
        dummy_img = np.zeros((1, 224, 224, 3), dtype=np.float32)
        self.model_1.predict(dummy_img, verbose=0)
        self.model_2.predict(dummy_img, verbose=0)
        
        init_db()
        console.print("[green]Models and DB loaded successfully.[/green]")

    def preprocess_stage1(self, frame):
        """Preprocesses frame for Stage 1 INT8 MobileNetV3."""
        img = cv2.resize(frame, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # INT8 model expects uint8 [0, 255]
        img = np.expand_dims(img, axis=0).astype(np.uint8)
        return img

    def preprocess_stage2(self, frame):
        """Preprocesses frame for Stage 2 Transformer (Float32)."""
        img = cv2.resize(frame, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # Assuming scaling was built into the model or expects 0-255 Float32
        img = np.expand_dims(img, axis=0).astype(np.float32)
        return img

    def predict(self, frame: np.ndarray, save_path: str = "") -> dict:
        """Runs the two-stage inference pipeline."""
        ts = datetime.now(timezone.utc).isoformat()
        
        # --- STAGE 1: SCREENING ---
        s1_input = self.preprocess_stage1(frame)
        is_diseased_s1, s1_score, s1_ms = self.run_stage_1(s1_input)
        
        if not is_diseased_s1:
            # HEALTHY - Stop early
            result = {
                "timestamp": ts, "crop": "Unknown", "disease": "HEALTHY",
                "confidence": round((1.0 - s1_score)*100, 1), # Invert score for healthy confidence
                "action": "No action needed.", "image_path": save_path,
                "stage1_inference_ms": round(s1_ms, 1), "stage2_inference_ms": 0,
                "is_diseased": False
            }
            log_detection(result)
            self._print_result(result)
            return result
            
        # --- STAGE 2: CLASSIFICATION ---
        s2_input = self.preprocess_stage2(frame)
        disease_name, confidence, action, s2_ms = self.run_stage_2(s2_input)
        
        # Parse crop from disease string (e.g. "Tomato___Bacterial_spot")
        crop = disease_name.split("___")[0] if "___" in disease_name else "Unknown"
        
        result = {
            "timestamp": ts, "crop": crop, "disease": disease_name.replace("___", " - "),
            "confidence": round(confidence*100, 1), "action": action,
            "image_path": save_path, "stage1_inference_ms": round(s1_ms, 1),
            "stage2_inference_ms": round(s2_ms, 1), "is_diseased": True
        }
        
        if save_path:
            cv2.imwrite(save_path, frame)
            
        log_detection(result)
        self._print_result(result)
        return result

    def _print_result(self, r: dict):
        table = Table(box=box.ROUNDED, show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        
        status_clr = "red" if r["is_diseased"] else "green"
        status_icon = "🚨" if r["is_diseased"] else "✅"
        
        table.add_row("Status", f"[{status_clr}]{status_icon} {r['disease']} ({r['confidence']}%)")
        if r["is_diseased"]:
            table.add_row("Action", f"[yellow]{r['action']}")
        
        table.add_row("Latency", f"[dim]S1: {r['stage1_inference_ms']}ms | S2: {r['stage2_inference_ms']}ms")
        console.print(table)


# ──────────────────────────────────────────────
# MAIN LOOP (CAMERA / SIMULATION)
# ──────────────────────────────────────────────
def run_loop():
    engine = EdgeBrainEngine()
    
    cap = cv2.VideoCapture(0)
    sim_mode = False
    
    if not cap.isOpened():
        console.print("[yellow]No camera detected. Entering SIMULATION MODE.[/yellow]")
        sim_mode = True
        Path(TEST_IMG_DIR).mkdir(parents=True, exist_ok=True)
        # Create a dummy test image if dir is empty
        if not list(Path(TEST_IMG_DIR).glob("*.jpg")):
            img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            cv2.imwrite(f"{TEST_IMG_DIR}/dummy.jpg", img)
            console.print(f"[dim]Generated dummy test image in {TEST_IMG_DIR}[/dim]")
            
    # Setup saves dir
    save_dir = "detections_log"
    Path(save_dir).mkdir(exist_ok=True)

    try:
        if sim_mode:
            images = list(Path(TEST_IMG_DIR).glob("*.jpg"))
            for img_path in images:
                frame = cv2.imread(str(img_path))
                save_path = f"{save_dir}/{int(time.time())}.jpg"
                engine.predict(frame, save_path)
                time.sleep(2)  # Simulate delay between drone shots
        else:
            console.print("[cyan]Press Ctrl+C to exit camera loop.[/cyan]")
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Only run inference every 2 seconds to save power
                save_path = f"{save_dir}/{int(time.time())}.jpg"
                engine.predict(frame, save_path)
                time.sleep(2)
                
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down EDGE-BRAIN...[/yellow]")
    finally:
        if not sim_mode:
            cap.release()

if __name__ == "__main__":
    run_loop()
