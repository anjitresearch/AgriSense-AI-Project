// ==============================================================
//  SKYWATCH-H™ — Drone Image Ingestion API (Node.js / Express)
//  Accepts RGB and hyperspectral image uploads from drone payloads
//  Forwards to EDGE-BRAIN™ for disease AI classification
//  Publishes flight metadata to MQTT broker
// ==============================================================

const express    = require("express");
const multer     = require("multer");
const axios      = require("axios");
const mqtt       = require("mqtt");
const fs         = require("fs");
const path       = require("path");
const cors       = require("cors");
const { v4: uuidv4 } = require("uuid");
const FormData   = require("form-data");

// ──────────────────────────────────────────────
// CONFIG
// ──────────────────────────────────────────────
const PORT            = process.env.PORT || 3001;
const EDGE_BRAIN_URL  = process.env.EDGE_BRAIN_URL || "http://localhost:8000";   // CONFIG_REQUIRED
const MQTT_BROKER     = process.env.MQTT_BROKER    || "mqtt://localhost:1883";   // CONFIG_REQUIRED
const UPLOAD_DIR      = process.env.UPLOAD_DIR     || "./uploads";
const MAX_FILE_MB     = 15;

// Ensure upload directory exists
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

// ──────────────────────────────────────────────
// MQTT CLIENT
// ──────────────────────────────────────────────
const mqttClient = mqtt.connect(MQTT_BROKER, {
  clientId: `skywatch-${Date.now()}`,
  reconnectPeriod: 5000,     // Auto-reconnect every 5 s
  connectTimeout: 10000,
});

mqttClient.on("connect", () => {
  console.log(`[SKYWATCH-H] MQTT connected to ${MQTT_BROKER}`);
});

mqttClient.on("error", (err) => {
  console.error(`[SKYWATCH-H] MQTT error: ${err.message}`);
});

// Helper: publish to MQTT with error handling
function mqttPublish(topic, payload) {
  try {
    mqttClient.publish(topic, JSON.stringify(payload), { qos: 1 });
  } catch (e) {
    console.error(`[SKYWATCH-H] MQTT publish failed: ${e.message}`);
  }
}

// ──────────────────────────────────────────────
// MULTER — File upload middleware
// Accepts JPEG, PNG, TIFF (hyperspectral)
// ──────────────────────────────────────────────
const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, UPLOAD_DIR),
  filename:    (req, file, cb) => {
    const ext = path.extname(file.originalname);
    cb(null, `${uuidv4()}${ext}`);
  },
});

const fileFilter = (req, file, cb) => {
  const allowed = ["image/jpeg", "image/png", "image/tiff", "image/webp"];
  if (allowed.includes(file.mimetype)) {
    cb(null, true);
  } else {
    cb(new Error(`Unsupported file type: ${file.mimetype}`), false);
  }
};

const upload = multer({
  storage,
  fileFilter,
  limits: { fileSize: MAX_FILE_MB * 1024 * 1024 },
});

// ──────────────────────────────────────────────
// EXPRESS APP
// ──────────────────────────────────────────────
const app = express();
app.use(cors());
app.use(express.json());
app.use("/uploads", express.static(UPLOAD_DIR));  // Serve uploaded images

// ──────────────────────────────────────────────
// POST /ingest — Main drone image ingestion endpoint
// Accepts: multipart/form-data with fields:
//   file       — image file (JPEG/PNG/TIFF)
//   flight_id  — drone flight UUID
//   field_id   — farm field identifier
//   gps_lat    — GPS latitude of image center
//   gps_lon    — GPS longitude
//   altitude_m — drone altitude in meters
//   image_type — "rgb" | "hyperspectral" | "ndvi"
// ──────────────────────────────────────────────
app.post("/ingest", upload.single("file"), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: "No image file provided" });
  }

  const ingestId  = uuidv4();
  const filePath  = req.file.path;
  const fileName  = req.file.filename;
  const timestamp = new Date().toISOString();

  // Extract flight metadata from form fields
  const metadata = {
    ingest_id:  ingestId,
    flight_id:  req.body.flight_id  || `FLIGHT-${Date.now()}`,
    field_id:   req.body.field_id   || "FIELD-001",
    gps_lat:    parseFloat(req.body.gps_lat)    || 11.0168,   // Default: Coimbatore, TN
    gps_lon:    parseFloat(req.body.gps_lon)    || 76.9558,
    altitude_m: parseFloat(req.body.altitude_m) || 30.0,
    image_type: req.body.image_type || "rgb",
    filename:   fileName,
    file_size_kb: Math.round(req.file.size / 1024),
    timestamp,
  };

  console.log(`[SKYWATCH-H] Ingested image: ${ingestId} | ${metadata.image_type} | ${metadata.file_size_kb} KB`);

  // Publish ingest event to MQTT
  mqttPublish("agrisense/skywatch/ingest", { ...metadata, status: "received" });

  // ── Forward to EDGE-BRAIN™ for AI disease classification ──
  let diseaseResult = null;
  try {
    const form = new FormData();
    form.append("file", fs.createReadStream(filePath), {
      filename:    req.file.originalname,
      contentType: req.file.mimetype,
    });

    const response = await axios.post(
      `${EDGE_BRAIN_URL}/predict/disease`,
      form,
      { headers: form.getHeaders(), timeout: 30000 }
    );
    diseaseResult = response.data;

    // Publish disease alert to MQTT if non-healthy result
    if (diseaseResult.disease !== "Healthy") {
      mqttPublish("agrisense/skywatch/disease_alert", {
        ingest_id:  ingestId,
        field_id:   metadata.field_id,
        flight_id:  metadata.flight_id,
        gps_lat:    metadata.gps_lat,
        gps_lon:    metadata.gps_lon,
        disease:    diseaseResult.disease,
        confidence: diseaseResult.confidence,
        severity:   diseaseResult.severity,
        timestamp,
      });
      console.log(`[SKYWATCH-H] DISEASE ALERT: ${diseaseResult.disease} (${diseaseResult.confidence}%) at ${metadata.field_id}`);
    }

  } catch (err) {
    // Edge Brain unavailable — log and continue (non-blocking)
    console.warn(`[SKYWATCH-H] Edge Brain unreachable: ${err.message}`);
    diseaseResult = {
      disease: "UNKNOWN",
      confidence: 0,
      severity: "unknown",
      note: "Edge Brain inference unavailable",
    };
  }

  // Build and return full response
  const result = {
    status:        "ok",
    ingest_id:     ingestId,
    file_url:      `/uploads/${fileName}`,
    metadata,
    disease_result: diseaseResult,
    timestamp,
  };

  // Publish complete analysis event
  mqttPublish("agrisense/skywatch/analysis_complete", result);

  return res.status(200).json(result);
});


// ──────────────────────────────────────────────
// GET /flights — List recent drone flight records
// ──────────────────────────────────────────────
app.get("/flights", (req, res) => {
  try {
    const files = fs.readdirSync(UPLOAD_DIR)
      .filter(f => [".jpg", ".jpeg", ".png", ".tiff"].includes(path.extname(f).toLowerCase()))
      .map(f => {
        const stat = fs.statSync(path.join(UPLOAD_DIR, f));
        return {
          filename:    f,
          url:         `/uploads/${f}`,
          size_kb:     Math.round(stat.size / 1024),
          uploaded_at: stat.mtime.toISOString(),
        };
      })
      .sort((a, b) => new Date(b.uploaded_at) - new Date(a.uploaded_at))
      .slice(0, 50);   // Last 50 images

    res.json({ count: files.length, images: files });
  } catch (e) {
    res.status(500).json({ error: "Failed to read uploads directory" });
  }
});


// ──────────────────────────────────────────────
// GET /simulate — Simulate a drone flight with a test image
// Generates a synthetic NDVI-colored image for testing
// ──────────────────────────────────────────────
app.get("/simulate", async (req, res) => {
  const fieldId  = req.query.field_id || "FIELD-SIM-001";
  const flightId = `SIM-${Date.now()}`;

  // Publish simulated flight metadata to MQTT
  const simPayload = {
    flight_id:  flightId,
    field_id:   fieldId,
    gps_lat:    11.0168 + Math.random() * 0.01,
    gps_lon:    76.9558 + Math.random() * 0.01,
    altitude_m: 25 + Math.random() * 15,
    image_type: "ndvi",
    simulated:  true,
    timestamp:  new Date().toISOString(),
  };

  mqttPublish("agrisense/skywatch/simulated_flight", simPayload);

  // Simulate disease detection result
  const diseases = ["Healthy", "Healthy", "Healthy", "Leaf_Blight", "Powdery_Mildew"];
  const disease  = diseases[Math.floor(Math.random() * diseases.length)];
  const severity_map = { Healthy: "none", Leaf_Blight: "high", Powdery_Mildew: "medium" };

  res.json({
    status:       "simulated",
    flight_id:    flightId,
    field_id:     fieldId,
    metadata:     simPayload,
    disease_result: {
      disease:    disease,
      confidence: 75 + Math.random() * 23,
      severity:   severity_map[disease] || "unknown",
      note:       "SIMULATED — no real image uploaded",
    },
    timestamp: new Date().toISOString(),
  });
});


// ──────────────────────────────────────────────
// GET /health
// ──────────────────────────────────────────────
app.get("/health", (req, res) => {
  res.json({
    service:      "SKYWATCH-H™",
    status:       "healthy",
    mqtt:         mqttClient.connected ? "connected" : "disconnected",
    edge_brain:   EDGE_BRAIN_URL,
    upload_dir:   UPLOAD_DIR,
    timestamp:    new Date().toISOString(),
  });
});


// ──────────────────────────────────────────────
// Error handling middleware
// ──────────────────────────────────────────────
app.use((err, req, res, next) => {
  if (err.code === "LIMIT_FILE_SIZE") {
    return res.status(413).json({ error: `File too large (max ${MAX_FILE_MB} MB)` });
  }
  console.error(`[SKYWATCH-H] Unhandled error: ${err.message}`);
  res.status(500).json({ error: err.message });
});


// ──────────────────────────────────────────────
// START SERVER
// ──────────────────────────────────────────────
app.listen(PORT, "0.0.0.0", () => {
  console.log(`[SKYWATCH-H™] Drone ingestion API running on port ${PORT}`);
  console.log(`  → Edge Brain:  ${EDGE_BRAIN_URL}`);
  console.log(`  → MQTT Broker: ${MQTT_BROKER}`);
  console.log(`  → Upload Dir:  ${UPLOAD_DIR}`);
});

module.exports = app;
