# ==============================================================
#  NUTRA-SPEC™ — PLSR Phytochemical Predictor Training Script
#  Trains a Partial Least Squares Regression model to predict
#  phytochemical concentrations from NIR spectra (900–1700 nm)
#  Output: nutra_plsr.pkl — saved model for EDGE-BRAIN™ API
# ==============================================================

import numpy as np
import pandas as pd
import pickle
import os
import json
import logging
from datetime import datetime

from sklearn.cross_decomposition import PLSRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, KFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for headless Raspberry Pi
import matplotlib.pyplot as plt

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
RANDOM_SEED    = 42
N_COMPONENTS   = 8        # PLSR latent variables (tune via cross-validation)
TEST_SPLIT     = 0.2
N_CV_FOLDS     = 5
OUTPUT_DIR     = "./models"
MODEL_FILENAME = "nutra_plsr.pkl"
REPORT_FILE    = "nutra_training_report.json"

# NIR wavelength range for simulation (25 bands from 900–1700 nm)
WAVELENGTHS    = np.linspace(900, 1700, 25)

# Phytochemical targets (mg/100g fresh weight unless noted)
TARGET_NAMES   = [
    "flavonoids_mg",       # Flavonoids
    "anthocyanins_mg",     # Anthocyanins
    "lycopene_mg",         # Lycopene
    "vitamin_c_mg",        # Vitamin C (ascorbic acid)
    "total_phenols_mg",    # Total phenolics (mg GAE/100g)
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [NUTRA-SPEC] %(levelname)s — %(message)s")
logger = logging.getLogger("nutra_spec")

np.random.seed(RANDOM_SEED)


# ==============================================================
#  SYNTHETIC DATASET GENERATOR
#  Simulates realistic NIR spectra + phytochemical reference data
#  Replace with real spectrophotometer CSV data for production
# ==============================================================
def generate_synthetic_nir_dataset(n_samples: int = 500):
    """
    Generate synthetic NIR spectra for common crops: tomato, pepper, spinach, strawberry.
    Each crop has characteristic absorption peaks that correlate with phytochemicals.
    In production: load exported CSV from FOSS XDS or similar NIR instrument.
    """
    n_wavelengths = len(WAVELENGTHS)
    X = np.zeros((n_samples, n_wavelengths))
    Y = np.zeros((n_samples, len(TARGET_NAMES)))

    crop_profiles = {
        "tomato":     {"base": 0.35, "lycopene_factor": 2.5, "vitamin_c_factor": 1.2},
        "pepper":     {"base": 0.28, "lycopene_factor": 1.8, "vitamin_c_factor": 2.0},
        "spinach":    {"base": 0.42, "lycopene_factor": 0.3, "vitamin_c_factor": 1.5},
        "strawberry": {"base": 0.30, "lycopene_factor": 0.5, "vitamin_c_factor": 1.8},
    }

    for i in range(n_samples):
        crop = list(crop_profiles.keys())[i % len(crop_profiles)]
        p    = crop_profiles[crop]

        # Simulate NIR reflectance curve with Gaussian peaks
        # Peak at ~960 nm (O-H 3rd overtone), ~1200 nm (C-H 2nd overtone), ~1450 nm (O-H 1st overtone)
        base_reflectance = p["base"] + np.random.normal(0, 0.02, n_wavelengths)
        water_band       = 0.15 * np.exp(-0.5 * ((WAVELENGTHS - 1450) / 50) ** 2)
        ch_band          = 0.08 * np.exp(-0.5 * ((WAVELENGTHS - 1200) / 40) ** 2)
        oh_band          = 0.06 * np.exp(-0.5 * ((WAVELENGTHS - 960)  / 30) ** 2)
        noise            = np.random.normal(0, 0.005, n_wavelengths)

        # Lycopene & anthocyanin absorb in visible-NIR transition (~900–950 nm)
        lycopene_signal     = 0.03 * p["lycopene_factor"]   * np.exp(-0.5 * ((WAVELENGTHS - 920) / 25) ** 2)
        anthocyanin_signal  = 0.025 * np.random.uniform(0.8, 1.5) * np.exp(-0.5 * ((WAVELENGTHS - 945) / 20) ** 2)
        flavonoid_signal    = 0.02  * np.random.uniform(0.9, 1.4) * np.exp(-0.5 * ((WAVELENGTHS - 975) / 35) ** 2)

        X[i] = (base_reflectance - water_band - ch_band - oh_band
                + lycopene_signal + anthocyanin_signal + flavonoid_signal + noise)
        X[i] = np.clip(X[i], 0.01, 0.99)  # Physical bounds of reflectance

        # Reference wet-chemistry values correlated with spectral features
        lycopene_coeff = lycopene_signal.sum()
        antho_coeff    = anthocyanin_signal.sum()
        flav_coeff     = flavonoid_signal.sum()

        Y[i, 0] = 10 + 80  * flav_coeff    + np.random.normal(0, 3)      # flavonoids
        Y[i, 1] = 5  + 60  * antho_coeff   + np.random.normal(0, 2)      # anthocyanins
        Y[i, 2] = 8  + 100 * lycopene_coeff + np.random.normal(0, 2.5)   # lycopene
        Y[i, 3] = 15 + 50  * p["vitamin_c_factor"] * (1 + np.random.normal(0, 0.1))  # vit C
        Y[i, 4] = 50 + 200 * (flav_coeff + antho_coeff) + np.random.normal(0, 10)    # total phenols

    # Clip to plausible ranges
    Y = np.clip(Y, 0, None)
    return X, Y


# ==============================================================
#  OPTIONAL: Load real CSV data
#  CSV format: [wavelength columns..., flavonoids, anthocyanins,
#               lycopene, vitamin_c, total_phenols]
# ==============================================================
def load_real_dataset(csv_path: str):
    """
    Load real NIR + wet-chemistry CSV dataset.
    Expected columns: w900, w920, ..., w1700 (wavelength reflectance),
                      then target columns in TARGET_NAMES order.
    """
    df = pd.read_csv(csv_path)
    n_spectral = len(WAVELENGTHS)
    X = df.iloc[:, :n_spectral].values.astype(np.float32)
    Y = df.iloc[:, n_spectral:n_spectral + len(TARGET_NAMES)].values.astype(np.float32)
    logger.info(f"Loaded real dataset: {X.shape[0]} samples, {X.shape[1]} wavelengths")
    return X, Y


# ==============================================================
#  PREPROCESSING — Standard Normal Variate (SNV) transformation
#  Removes baseline drift and multiplicative scatter in NIR
# ==============================================================
def snv_transform(X: np.ndarray) -> np.ndarray:
    """
    Standard Normal Variate (SNV) — industry standard for NIR preprocessing.
    Centers each spectrum and scales by its own standard deviation.
    """
    X_snv = np.zeros_like(X)
    for i in range(X.shape[0]):
        mean = np.mean(X[i])
        std  = np.std(X[i])
        X_snv[i] = (X[i] - mean) / (std + 1e-8)
    return X_snv


# ==============================================================
#  CROSS-VALIDATION: Find optimal number of PLSR components
# ==============================================================
def find_optimal_components(X_train, Y_train, max_components=15):
    """Test 1..max_components and return the component count with lowest RMSE."""
    cv = KFold(n_splits=N_CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    rmse_scores = []

    for n in range(1, max_components + 1):
        pls  = PLSRegression(n_components=n, max_iter=500)
        cv_scores = cross_val_score(pls, X_train, Y_train[:, 0],
                                    scoring="neg_mean_squared_error", cv=cv)
        rmse = np.sqrt(-cv_scores.mean())
        rmse_scores.append(rmse)
        logger.info(f"  n_components={n:2d} → RMSE={rmse:.4f}")

    best_n = int(np.argmin(rmse_scores)) + 1
    logger.info(f"  Optimal n_components = {best_n}")
    return best_n, rmse_scores


# ==============================================================
#  TRAINING PIPELINE
# ==============================================================
def train():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("NUTRA-SPEC™ PLSR Training — AgriSense-AI™")
    logger.info("=" * 60)

    # ── 1. Data loading ───────────────────────────────────────
    real_csv = "./data/nir_phytochem.csv"   # CONFIG_REQUIRED: path to real NIR CSV
    if os.path.exists(real_csv):
        logger.info(f"Loading real dataset from {real_csv}")
        X, Y = load_real_dataset(real_csv)
    else:
        logger.info("Real dataset not found — generating synthetic training data (500 samples)")
        X, Y = generate_synthetic_nir_dataset(n_samples=500)

    logger.info(f"Dataset shape: X={X.shape}, Y={Y.shape}")

    # ── 2. SNV Preprocessing ──────────────────────────────────
    logger.info("Applying SNV preprocessing…")
    X = snv_transform(X)

    # ── 3. Train / Test Split ─────────────────────────────────
    X_train, X_test, Y_train, Y_test = train_test_split(
        X, Y, test_size=TEST_SPLIT, random_state=RANDOM_SEED
    )
    logger.info(f"Train: {X_train.shape[0]} samples | Test: {X_test.shape[0]} samples")

    # ── 4. Feature Scaling ────────────────────────────────────
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    # ── 5. Optimize n_components via cross-validation ─────────
    logger.info("Cross-validating to find optimal PLSR components…")
    best_n, cv_rmse = find_optimal_components(X_train, Y_train, max_components=12)

    # ── 6. Train final PLSR model ─────────────────────────────
    logger.info(f"Training final PLS model with n_components={best_n}…")
    pls = PLSRegression(n_components=best_n, max_iter=1000)
    pls.fit(X_train, Y_train)

    # ── 7. Evaluate on test set ───────────────────────────────
    Y_pred = pls.predict(X_test)
    metrics = {}
    for j, name in enumerate(TARGET_NAMES):
        r2   = r2_score(Y_test[:, j], Y_pred[:, j])
        rmse = np.sqrt(mean_squared_error(Y_test[:, j], Y_pred[:, j]))
        mae  = mean_absolute_error(Y_test[:, j], Y_pred[:, j])
        metrics[name] = {"R2": round(r2, 4), "RMSE": round(rmse, 4), "MAE": round(mae, 4)}
        logger.info(f"  {name:<25} R²={r2:.4f} | RMSE={rmse:.4f} | MAE={mae:.4f}")

    # ── 8. Save model bundle (scaler + PLS) ───────────────────
    model_bundle = {
        "plsr":      pls,
        "scaler":    scaler,
        "targets":   TARGET_NAMES,
        "n_components":  best_n,
        "wavelengths":   WAVELENGTHS.tolist(),
        "trained_at":    start_time.isoformat(),
    }
    model_path = os.path.join(OUTPUT_DIR, MODEL_FILENAME)
    with open(model_path, "wb") as f:
        pickle.dump(model_bundle, f)
    logger.info(f"Model saved → {model_path}")

    # ── 9. Save training report ────────────────────────────────
    report = {
        "n_samples":    X.shape[0],
        "n_wavelengths": X.shape[1],
        "n_components": best_n,
        "n_targets":    len(TARGET_NAMES),
        "test_metrics": metrics,
        "trained_at":   start_time.isoformat(),
        "duration_s":   (datetime.now() - start_time).seconds,
    }
    report_path = os.path.join(OUTPUT_DIR, REPORT_FILE)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Report saved → {report_path}")

    # ── 10. Plot predicted vs actual for first target ──────────
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()
    for j, name in enumerate(TARGET_NAMES):
        ax = axes[j]
        ax.scatter(Y_test[:, j], Y_pred[:, j], alpha=0.6, color="#2ecc71", edgecolors="#27ae60", s=30)
        mn = min(Y_test[:, j].min(), Y_pred[:, j].min())
        mx = max(Y_test[:, j].max(), Y_pred[:, j].max())
        ax.plot([mn, mx], [mn, mx], "r--", lw=1.5, label="1:1 line")
        ax.set_xlabel("Actual (mg/100g)")
        ax.set_ylabel("Predicted (mg/100g)")
        ax.set_title(f"{name}\nR²={metrics[name]['R²']:.3f}" if "R²" in metrics[name]
                     else f"{name}\nR²={metrics[name]['R2']:.3f}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # CV RMSE plot
    ax = axes[len(TARGET_NAMES)]
    ax.plot(range(1, len(cv_rmse) + 1), cv_rmse, "bo-", ms=6)
    ax.axvline(best_n, color="red", linestyle="--", label=f"Optimal={best_n}")
    ax.set_xlabel("Number of Components")
    ax.set_ylabel("CV RMSE")
    ax.set_title("Cross-Validation Component Selection")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.suptitle("NUTRA-SPEC™ PLSR Model — Predicted vs Actual", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, "nutra_plsr_performance.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Performance plot → {plot_path}")
    logger.info("Training complete!")
    return model_bundle


# ──────────────────────────────────────────────
# INFERENCE HELPER — used by edge_brain_api.py
# ──────────────────────────────────────────────
class NutraSpecPredictor:
    """Wrapper class for loading and using the trained PLSR bundle."""
    def __init__(self, model_path: str):
        with open(model_path, "rb") as f:
            bundle = pickle.load(f)
        self.pls     = bundle["plsr"]
        self.scaler  = bundle["scaler"]
        self.targets = bundle["targets"]

    def predict(self, nir_spectrum: np.ndarray) -> dict:
        """Predict phytochemicals from raw NIR spectrum (no SNV needed if pre-applied)."""
        X = snv_transform(nir_spectrum.reshape(1, -1))
        X = self.scaler.transform(X)
        preds = self.pls.predict(X)[0]
        return {name: round(float(val), 3) for name, val in zip(self.targets, preds)}


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    train()
