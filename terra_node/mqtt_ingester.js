/**
 * ==============================================================
 *  TERRA-NODE™ — MQTT Ingester (Node.js)
 *  Subscribes to agrisense/+/soil
 *  Validates payload schema
 *  Writes to InfluxDB bucket "soil_data"
 *  Triggers alerts on out-of-bounds readings
 * ==============================================================
 */

const mqtt = require('mqtt');
const { InfluxDB, Point } = require('@influxdata/influxdb-client');

// --- Configuration ---
const MQTT_BROKER = process.env.MQTT_BROKER || 'mqtt://localhost:1883';
const INFLUX_URL = process.env.INFLUX_URL || 'http://localhost:8086';
const INFLUX_TOKEN = process.env.INFLUX_TOKEN || 'agrisense-super-secret-token';
const INFLUX_ORG = process.env.INFLUX_ORG || 'agrisense';
const INFLUX_BUCKET = process.env.INFLUX_BUCKET || 'soil_data';

// --- MQTT Setup ---
console.log(`[INGESTER] Connecting to MQTT broker at ${MQTT_BROKER}...`);
const mqttClient = mqtt.connect(MQTT_BROKER);

// --- InfluxDB Setup ---
console.log(`[INGESTER] Configuring InfluxDB client for ${INFLUX_URL}...`);
const influxDB = new InfluxDB({ url: INFLUX_URL, token: INFLUX_TOKEN });
const writeApi = influxDB.getWriteApi(INFLUX_ORG, INFLUX_BUCKET, 'ns');

// Handle exit cleanly to flush InfluxDB writes
const flushAndExit = async () => {
    console.log('\n[INGESTER] Flushing data and shutting down...');
    try {
        await writeApi.close();
        console.log('[INGESTER] InfluxDB write API closed.');
    } catch (e) {
        console.error('[INGESTER] Error closing InfluxDB API:', e);
    }
    process.exit(0);
};

process.on('SIGINT', flushAndExit);
process.on('SIGTERM', flushAndExit);

// --- Alert Thresholds ---
const ALERTS = {
    ph_min: 5.5,
    ph_max: 8.0,
    moisture_min: 20.0,
    n_min: 50,
    p_min: 20,
    k_min: 30
};

/**
 * Validates the raw JSON payload against the expected schema.
 */
function validatePayload(data) {
    if (!data.device_id || !data.timestamp || !data.npk) {
        throw new Error('Missing top-level fields (device_id, timestamp, npk)');
    }
    if (typeof data.pH !== 'number' || typeof data.moisture !== 'number' || typeof data.EC !== 'number') {
        throw new Error('Invalid or missing numeric values for pH, moisture, or EC');
    }
    if (typeof data.npk.N !== 'number' || typeof data.npk.P !== 'number' || typeof data.npk.K !== 'number') {
        throw new Error('Invalid or missing numeric values for NPK');
    }
    return true;
}

/**
 * Checks readings against agronomic thresholds and logs alerts.
 */
function checkAlerts(data, farmId) {
    const alerts = [];

    if (data.pH < ALERTS.ph_min || data.pH > ALERTS.ph_max) {
        alerts.push(`pH out of bounds (${data.pH})`);
    }
    if (data.moisture < ALERTS.moisture_min) {
        alerts.push(`Critical low moisture (${data.moisture}%)`);
    }
    if (data.npk.N < ALERTS.n_min || data.npk.P < ALERTS.p_min || data.npk.K < ALERTS.k_min) {
        alerts.push(`Low nutrients detected (N:${data.npk.N}, P:${data.npk.P}, K:${data.npk.K})`);
    }

    if (alerts.length > 0) {
        console.warn(`\n🚨 [ALERT] TERRA-NODE [${data.device_id}] at [${farmId}]:`);
        alerts.forEach(a => console.warn(`   - ${a}`));
    }
}

// --- MQTT Event Handlers ---
mqttClient.on('connect', () => {
    const topic = 'agrisense/+/soil';
    console.log(`[INGESTER] Connected to MQTT broker. Subscribing to: ${topic}`);
    mqttClient.subscribe(topic, (err) => {
        if (err) console.error('[INGESTER] Subscription error:', err);
    });
});

mqttClient.on('message', (topic, message) => {
    console.log(`\n[INGESTER] Received message on topic: ${topic}`);

    // Extract farm_id from topic (e.g., agrisense/farm001/soil)
    const topicParts = topic.split('/');
    const farmId = topicParts[1] || 'unknown_farm';

    try {
        const payload = JSON.parse(message.toString());

        // 1. Validate
        validatePayload(payload);

        // 2. Alert Generation
        checkAlerts(payload, farmId);

        // 3. Write to InfluxDB
        const point = new Point('soil_reading')
            .tag('farm_id', farmId)
            .tag('device_id', payload.device_id)
            .floatField('nitrogen', payload.npk.N)
            .floatField('phosphorus', payload.npk.P)
            .floatField('potassium', payload.npk.K)
            .floatField('pH', payload.pH)
            .floatField('EC', payload.EC)
            .floatField('moisture', payload.moisture)
            .floatField('temperature', payload.temperature || 0.0)
            .floatField('battery_pct', payload.battery_pct || 0.0);

        // Optionally override Timestamp if provided by sensor, 
        // else rely on InfluxDB server time
        // point.timestamp(new Date(payload.timestamp));

        writeApi.writePoint(point);
        console.log(`[INGESTER] ✅ Validated and written to InfluxDB: ${payload.device_id}`);

    } catch (err) {
        console.error(`[INGESTER] ❌ Payload Error: ${err.message}`);
    }
});
