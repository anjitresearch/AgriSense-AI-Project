"""
==============================================================
 EDGE-BRAIN™ — model_trainer.py
 Two-Stage TinyML Pipeline for Crop Disease Detection
 
 STAGE 1: MobileNetV3-Small (Binary: Healthy vs Diseased)
 STAGE 2: Lightweight 4-Head Self-Attention Transformer
 
 Dataset: PlantVillage (Subset)
 Run: python model_trainer.py
==============================================================
"""

import os
import urllib.request
import zipfile
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, Model
import logging
from pathlib import Path

# ──────────────────────────────────────────────
# LOGGING CONFIG
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TRAINER] %(message)s")
logger = logging.getLogger("edge_brain_trainer")

# ──────────────────────────────────────────────
# HYPERPARAMETERS
# ──────────────────────────────────────────────
IMG_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 10  # Low epochs for demonstration; increase for production
DATA_DIR = "dataset/plantvillage"
MODEL_DIR = "models"
STAGE1_MODEL_PATH = f"{MODEL_DIR}/stage1_mobilenetv3.h5"
STAGE2_MODEL_PATH = f"{MODEL_DIR}/stage2_transformer.h5"

# 10 Simulated realistic disease classes
DISEASE_CLASSES = [
    "Tomato___Bacterial_spot",
    "Tomato___Early_blight",
    "Tomato___Late_blight",
    "Tomato___Leaf_Mold",
    "Tomato___Septoria_leaf_spot",
    "Tomato___Spider_mites Two-spotted_spider_mite",
    "Tomato___Target_Spot",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus",
    "Tomato___Tomato_mosaic_virus",
    "Rice___Brown_Spot"
]


def download_plantvillage_subset():
    """
    Simulates downloading a subset of the PlantVillage dataset for training.
    For this mock implementation, it generates synthetic image data.
    """
    logger.info("Setting up dataset directory...")
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(f"{DATA_DIR}/train/Healthy").mkdir(parents=True, exist_ok=True)
    Path(f"{DATA_DIR}/train/Diseased").mkdir(parents=True, exist_ok=True)
    for c in DISEASE_CLASSES:
        Path(f"{DATA_DIR}/train/{c}").mkdir(parents=True, exist_ok=True)
    logger.info("Dataset directories created. (Generating synthetic data in memory for this run).")


def build_stage1_mobilenet():
    """
    Builds and trains Stage 1: MobileNetV3-Small for Binary Classification (Healthy vs Diseased)
    """
    logger.info("Building Stage 1: MobileNetV3-Small (Binary Classification)...")
    
    # Base model pre-trained on ImageNet
    base_model = tf.keras.applications.MobileNetV3Small(
        input_shape=(IMG_SIZE, IMG_SIZE, 3),
        include_top=False,
        weights='imagenet',
        minimalistic=True  # Optimised for edge
    )
    base_model.trainable = False

    # Classification head
    inputs = tf.keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
    # MobileNetV3 expects [-1, 1] input.
    x = tf.keras.layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = base_model(x, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.2)(x)
    outputs = layers.Dense(1, activation='sigmoid')(x)  # 0=Healthy, 1=Diseased

    model = tf.keras.Model(inputs, outputs)
    
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
                  loss=tf.keras.losses.BinaryCrossentropy(),
                  metrics=['accuracy'])

    # --- SYNTHETIC TRAINING ---
    logger.info("Training Stage 1 model on synthetic data...")
    dummy_x = np.random.rand(100, IMG_SIZE, IMG_SIZE, 3).astype(np.float32)
    dummy_y = np.random.randint(0, 2, 100).astype(np.float32)
    model.fit(dummy_x, dummy_y, epochs=2, batch_size=32, verbose=1)

    Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
    model.save(STAGE1_MODEL_PATH)
    logger.info(f"Stage 1 Keras model saved to {STAGE1_MODEL_PATH}")


def mlp(x, hidden_units, dropout_rate):
    """Multi-Layer Perceptron block for the Transformer."""
    for units in hidden_units:
        x = layers.Dense(units, activation=tf.nn.gelu)(x)
        x = layers.Dropout(dropout_rate)(x)
    return x


def build_stage2_transformer():
    """
    Builds and trains Stage 2: Lightweight 4-Head Self-Attention Vision Transformer (ViT)
    Classifies 10 specific diseases.
    """
    logger.info("Building Stage 2: Lightweight 4-Head Transformer...")
    
    # ViT Hyperparameters specifically tuned for <5MB size
    patch_size = 16
    num_patches = (IMG_SIZE // patch_size) ** 2
    projection_dim = 64
    num_heads = 4
    transformer_layers = 4
    transformer_units = [projection_dim * 2, projection_dim]
    mlp_head_units = [512, 256]

    inputs = layers.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
    
    # Simple patch extraction using Conv2D (more efficient than extract_patches ops on Edge)
    patches = layers.Conv2D(projection_dim, kernel_size=patch_size, strides=patch_size)(inputs)
    patches = layers.Reshape((num_patches, projection_dim))(patches)
    
    # Add positional embedding
    positions = tf.range(start=0, limit=num_patches, delta=1)
    pos_emb = layers.Embedding(input_dim=num_patches, output_dim=projection_dim)(positions)
    encoded_patches = patches + pos_emb

    # Transformer Blocks
    for _ in range(transformer_layers):
        x1 = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
        attention_output = layers.MultiHeadAttention(num_heads=num_heads, key_dim=projection_dim, dropout=0.1)(x1, x1)
        x2 = layers.Add()([attention_output, encoded_patches])
        
        x3 = layers.LayerNormalization(epsilon=1e-6)(x2)
        x3 = mlp(x3, hidden_units=transformer_units, dropout_rate=0.1)
        encoded_patches = layers.Add()([x3, x2])

    # Global representation
    representation = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
    representation = layers.GlobalAveragePooling1D()(representation)
    representation = layers.Dropout(0.2)(representation)
    
    # Classification Head
    features = mlp(representation, hidden_units=mlp_head_units, dropout_rate=0.2)
    outputs = layers.Dense(len(DISEASE_CLASSES), activation="softmax")(features)

    model = Model(inputs=inputs, outputs=outputs)
    
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(),
                  metrics=['accuracy'])
                  
    model.summary(print_fn=logger.info)

    # --- SYNTHETIC TRAINING ---
    logger.info("Training Stage 2 Transformer model on synthetic data...")
    dummy_x = np.random.rand(100, IMG_SIZE, IMG_SIZE, 3).astype(np.float32)
    dummy_y = np.random.randint(0, len(DISEASE_CLASSES), 100).astype(np.float32)
    model.fit(dummy_x, dummy_y, epochs=2, batch_size=16, verbose=1)

    model.save(STAGE2_MODEL_PATH)
    logger.info(f"Stage 2 Keras model saved to {STAGE2_MODEL_PATH}")


if __name__ == "__main__":
    logger.info("Starting EDGE-BRAIN Training Pipeline...")
    download_plantvillage_subset()
    build_stage1_mobilenet()
    build_stage2_transformer()
    logger.info("Training complete. Models are ready for edge inference.")
