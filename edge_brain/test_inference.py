"""
==============================================================
 EDGE-BRAIN™ — test_inference.py
 Unit tests for the two-stage TinyML inference pipeline.
 
 Covers:
 1. Model Loading
 2. Stage 1 Binary Classification Threshold Limits
 3. Stage 2 Multi-Class Transformer Validation
 4. End-to-End Pipeline Execution (Image -> SQLite)
==============================================================
"""

import unittest
import numpy as np
import cv2
import sqlite3
import os
from edge_brain_inference import EdgeBrainEngine, init_db, DB_PATH, STAGE1_THRESHOLD, DISEASE_CLASSES

class TestEdgeBrainInference(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Initialise models and DB before all tests."""
        # Ensure models exist; if not, test will fail quickly
        cls.engine = EdgeBrainEngine()
        init_db()

    def setUp(self):
        """Clean database before each test."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM detections")
        conn.commit()
        conn.close()

    def test_model_initialization(self):
        """Test if both Stage 1 and Stage 2 models loaded successfully."""
        self.assertIsNotNone(self.engine.stage1, "Stage 1 model failed to load.")
        self.assertIsNotNone(self.engine.stage2, "Stage 2 model failed to load.")

    def test_preprocess_stage1(self):
        """Test Stage 1 specific preprocessing (INT8 [0,255])."""
        dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        processed = self.engine.preprocess_stage1(dummy_frame)
        self.assertEqual(processed.shape, (1, 224, 224, 3))
        self.assertEqual(processed.dtype, np.uint8)

    def test_preprocess_stage2(self):
        """Test Stage 2 specific preprocessing (Float32)."""
        dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        processed = self.engine.preprocess_stage2(dummy_frame)
        self.assertEqual(processed.shape, (1, 224, 224, 3))
        self.assertEqual(processed.dtype, np.float32)

    def test_end_to_end_inference_sick(self):
        """Test full pipeline. It will likely trigger Stage 2 because random noise usually triggers anomalous patterns."""
        dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        
        result = self.engine.predict(dummy_frame, save_path="")
        
        self.assertIn("timestamp", result)
        self.assertIn("disease", result)
        self.assertIn("confidence", result)
        self.assertIn("stage1_inference_ms", result)
        
        # Verify SQL logging
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT count(*) FROM detections')
        count = c.fetchone()[0]
        conn.close()
        
        self.assertEqual(count, 1, "Detection was not logged to SQLite DB.")

    def test_early_exit_healthy(self):
        """Force a healthy outcome by manipulating the threshold (for testing purposes)."""
        # Hack the instance threshold to a very high value to force healthy
        global STAGE1_THRESHOLD
        original_threshold = STAGE1_THRESHOLD
        
        # Set threshold to 1.1 (impossible score), forcing early exit
        import edge_brain_inference
        edge_brain_inference.STAGE1_THRESHOLD = 1.1
        
        dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = self.engine.predict(dummy_frame, save_path="")
        
        self.assertEqual(result["disease"], "HEALTHY")
        self.assertFalse(result["is_diseased"])
        self.assertEqual(result["stage2_inference_ms"], 0, "Stage 2 was executed despite healthy Stage 1 result.")
        
        # Restore actual threshold
        edge_brain_inference.STAGE1_THRESHOLD = original_threshold


if __name__ == '__main__':
    unittest.main()
