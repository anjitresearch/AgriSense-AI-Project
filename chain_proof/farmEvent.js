// ==============================================================
//  CHAIN-PROOF™ — Hyperledger Fabric Smart Contract (Chaincode)
//  Immutable AgriSense-AI™ farm event logger on permissioned blockchain
//
//  Ledger Objects:
//    FarmEvent  — any sensor, spray, harvest, or disease event
//    Certificate — phytochemical + provenance certificate NFT-equivalent
//
//  Endorsed by: Farmer-MSP, Auditor-MSP
//  Channel:     agrisense-channel
//
//  Compile & Deploy:
//    peer chaincode package farmEvent.tar.gz --path ./chain_proof --lang node --label farmEvent_1.0
//    peer lifecycle chaincode install farmEvent.tar.gz
//    peer lifecycle chaincode approveformyorg ...
//    peer lifecycle chaincode commit ...
// ==============================================================

"use strict";

const { Contract, Context } = require("fabric-contract-api");

// ──────────────────────────────────────────────
// CONSTANTS
// ──────────────────────────────────────────────
const EventType = Object.freeze({
    SOIL_READING: "SOIL_READING",      // Terra-Node NPK/pH/EC sensor data
    DISEASE_ALERT: "DISEASE_ALERT",     // Edge-Brain AI classification result
    DRONE_FLIGHT: "DRONE_FLIGHT",      // Skywatch-H ingestion metadata
    SPRAY_LOG: "SPRAY_LOG",         // Pesticide / fertiliser application
    HARVEST: "HARVEST",           // Harvest event with yield data
    NUTRA_CERT: "NUTRA_CERT",        // NUTRA-SPEC phytochemical certificate
    WEATHER: "WEATHER",           // Weather station reading
    IRRIGATION: "IRRIGATION",        // Irrigation event
});

const CERT_PREFIX = "CERT~";
const EVENT_PREFIX = "EVT~";
const IDX_FIELD = "FIELD_IDX~";   // Composite key prefix for field queries


// ──────────────────────────────────────────────
// CUSTOM CONTEXT — injects helper on ctx
// ──────────────────────────────────────────────
class AgriSenseContext extends Context {
    constructor() {
        super();
    }

    /**
     * Build a deterministic event ID from type + device + timestamp.
     * Uses ISO timestamp ms to avoid collisions in rapid sequences.
     */
    static makeEventId(eventType, deviceId, isoTimestamp) {
        const ts = new Date(isoTimestamp).getTime();
        return `${EVENT_PREFIX}${eventType}~${deviceId}~${ts}`;
    }

    static makeCertId(sampleId, isoTimestamp) {
        const ts = new Date(isoTimestamp).getTime();
        return `${CERT_PREFIX}${sampleId}~${ts}`;
    }
}


// ==============================================================
//  SMART CONTRACT CLASS
// ==============================================================
class FarmEventContract extends Contract {

    constructor() {
        super("FarmEventContract");
        this.createContext = () => new AgriSenseContext();
    }


    // ============================================================
    //  INIT LEDGER — seeds genesis block with platform metadata
    // ============================================================
    async initLedger(ctx) {
        const genesis = {
            docType: "genesis",
            platform: "AgriSense-AI™",
            version: "1.0.0",
            initialized: new Date().toISOString(),
            description: "AgriSense-AI precision agriculture blockchain — CHAIN-PROOF™",
        };
        await ctx.stub.putState("GENESIS", Buffer.from(JSON.stringify(genesis)));
        console.log("[CHAIN-PROOF] Ledger initialized with genesis block");
        return JSON.stringify(genesis);
    }


    // ============================================================
    //  logSoilReading
    //  Called by TERRA-NODE™ MQTT bridge after each sensor publish
    //  Parameters (all strings for Fabric CLI compatibility):
    //    deviceId, fieldId, nitrogen, phosphorus, potassium,
    //    pH, EC, moisture, soilTempC, timestamp
    // ============================================================
    async logSoilReading(ctx,
        deviceId, fieldId, nitrogen, phosphorus, potassium,
        pH, EC, moisture, soilTempC, timestamp
    ) {
        _requireRole(ctx, ["FarmerMSP", "AuditorMSP"]);

        const id = AgriSenseContext.makeEventId(EventType.SOIL_READING, deviceId, timestamp);

        const event = {
            docType: "FarmEvent",
            eventId: id,
            eventType: EventType.SOIL_READING,
            deviceId,
            fieldId,
            timestamp,
            recordedAt: new Date().toISOString(),
            data: {
                nitrogen: _parseNum(nitrogen),    // mg/kg
                phosphorus: _parseNum(phosphorus),  // mg/kg
                potassium: _parseNum(potassium),   // mg/kg
                pH: _parseNum(pH),
                EC: _parseNum(EC),          // µS/cm
                moisture: _parseNum(moisture),    // %
                soilTempC: _parseNum(soilTempC),  // °C
            },
        };

        await ctx.stub.putState(id, Buffer.from(JSON.stringify(event)));

        // Composite key index: fieldId → eventId (enables GetStateByPartialCompositeKey)
        const compKey = ctx.stub.createCompositeKey(IDX_FIELD, [fieldId, id]);
        await ctx.stub.putState(compKey, Buffer.from("\u0000"));

        // Emit Fabric event for off-chain consumers
        ctx.stub.setEvent("SoilReadingLogged", Buffer.from(JSON.stringify({ id, fieldId, deviceId, timestamp })));

        console.log(`[CHAIN-PROOF] Soil reading logged: ${id}`);
        return JSON.stringify(event);
    }


    // ============================================================
    //  logDiseaseAlert
    //  Called after EDGE-BRAIN™ classifies a disease from drone image
    // ============================================================
    async logDiseaseAlert(ctx,
        ingestId, fieldId, flightId,
        disease, confidence, severity,
        gpsLat, gpsLon, imageType, timestamp
    ) {
        _requireRole(ctx, ["FarmerMSP", "AuditorMSP"]);

        const id = AgriSenseContext.makeEventId(EventType.DISEASE_ALERT, ingestId, timestamp);

        const conf = _parseNum(confidence);
        if (conf < 0 || conf > 100) {
            throw new Error("confidence must be between 0 and 100");
        }

        const event = {
            docType: "FarmEvent",
            eventId: id,
            eventType: EventType.DISEASE_ALERT,
            ingestId,
            fieldId,
            flightId,
            timestamp,
            recordedAt: new Date().toISOString(),
            data: {
                disease,
                confidence: conf,          // %
                severity,                   // none | low | medium | high | critical
                gpsLat: _parseNum(gpsLat),
                gpsLon: _parseNum(gpsLon),
                imageType,                  // rgb | hyperspectral | ndvi
            },
        };

        await ctx.stub.putState(id, Buffer.from(JSON.stringify(event)));

        const compKey = ctx.stub.createCompositeKey(IDX_FIELD, [fieldId, id]);
        await ctx.stub.putState(compKey, Buffer.from("\u0000"));

        // If severity is high or critical, emit a special urgent alert event
        if (["high", "critical"].includes(severity.toLowerCase())) {
            ctx.stub.setEvent(
                "UrgentDiseaseAlert",
                Buffer.from(JSON.stringify({ id, fieldId, disease, severity, confidence: conf }))
            );
        }

        console.log(`[CHAIN-PROOF] Disease alert logged: ${id} — ${disease} (${severity})`);
        return JSON.stringify(event);
    }


    // ============================================================
    //  logDroneFlight
    //  Records SKYWATCH-H™ flight telemetry metadata
    // ============================================================
    async logDroneFlight(ctx,
        flightId, fieldId, gpsLat, gpsLon,
        altitudeM, imageType, imageCount, timestamp
    ) {
        _requireRole(ctx, ["FarmerMSP", "AuditorMSP"]);

        const id = AgriSenseContext.makeEventId(EventType.DRONE_FLIGHT, flightId, timestamp);

        const event = {
            docType: "FarmEvent",
            eventId: id,
            eventType: EventType.DRONE_FLIGHT,
            flightId,
            fieldId,
            timestamp,
            recordedAt: new Date().toISOString(),
            data: {
                gpsLat: _parseNum(gpsLat),
                gpsLon: _parseNum(gpsLon),
                altitudeM: _parseNum(altitudeM),
                imageType,
                imageCount: parseInt(imageCount, 10) || 1,
            },
        };

        await ctx.stub.putState(id, Buffer.from(JSON.stringify(event)));
        const compKey = ctx.stub.createCompositeKey(IDX_FIELD, [fieldId, id]);
        await ctx.stub.putState(compKey, Buffer.from("\u0000"));

        console.log(`[CHAIN-PROOF] Drone flight logged: ${id}`);
        return JSON.stringify(event);
    }


    // ============================================================
    //  issueNutraCertificate
    //  Mints an immutable phytochemical quality certificate
    //  tied to a specific harvest batch & NIR scan
    // ============================================================
    async issueNutraCertificate(ctx,
        sampleId, batchId, fieldId, cropType,
        flavonoids, anthocyanins, lycopene,
        vitaminC, totalPhenols,
        scanDeviceId, timestamp
    ) {
        _requireRole(ctx, ["FarmerMSP", "AuditorMSP"]);

        const certId = AgriSenseContext.makeCertId(sampleId, timestamp);

        // Check for duplicate certificate
        const existing = await ctx.stub.getState(certId);
        if (existing && existing.length > 0) {
            throw new Error(`Certificate ${certId} already exists on ledger`);
        }

        const certificate = {
            docType: "NutraCertificate",
            certId,
            sampleId,
            batchId,
            fieldId,
            cropType,
            scanDeviceId,
            issuedAt: new Date().toISOString(),
            timestamp,
            phytochemicals: {
                flavonoids_mg: _parseNum(flavonoids),      // mg/100g fresh weight
                anthocyanins_mg: _parseNum(anthocyanins),
                lycopene_mg: _parseNum(lycopene),
                vitamin_c_mg: _parseNum(vitaminC),
                total_phenols_mg: _parseNum(totalPhenols),    // mg GAE/100g
            },
            status: "VALID",    // VALID | REVOKED
            revoked_at: null,
        };

        await ctx.stub.putState(certId, Buffer.from(JSON.stringify(certificate)));

        // Index by fieldId for batch retrieval
        const compKey = ctx.stub.createCompositeKey(IDX_FIELD, [fieldId, certId]);
        await ctx.stub.putState(compKey, Buffer.from("\u0000"));

        ctx.stub.setEvent(
            "NutraCertificateIssued",
            Buffer.from(JSON.stringify({ certId, batchId, cropType, sampleId }))
        );

        console.log(`[CHAIN-PROOF] NutraCertificate issued: ${certId}`);
        return JSON.stringify(certificate);
    }


    // ============================================================
    //  revokeCertificate — marks cert REVOKED (cannot be deleted)
    // ============================================================
    async revokeCertificate(ctx, certId, reason) {
        _requireRole(ctx, ["AuditorMSP"]);  // Only auditor can revoke

        const certBytes = await ctx.stub.getState(certId);
        if (!certBytes || certBytes.length === 0) {
            throw new Error(`Certificate ${certId} not found`);
        }

        const cert = JSON.parse(certBytes.toString());
        if (cert.status === "REVOKED") {
            throw new Error(`Certificate ${certId} is already revoked`);
        }

        cert.status = "REVOKED";
        cert.revoked_at = new Date().toISOString();
        cert.revoke_reason = reason || "No reason provided";

        await ctx.stub.putState(certId, Buffer.from(JSON.stringify(cert)));

        ctx.stub.setEvent(
            "CertificateRevoked",
            Buffer.from(JSON.stringify({ certId, reason, revoked_at: cert.revoked_at }))
        );

        console.log(`[CHAIN-PROOF] Certificate revoked: ${certId}`);
        return JSON.stringify(cert);
    }


    // ============================================================
    //  QUERY FUNCTIONS
    // ============================================================

    /** Read a single event or certificate by key */
    async readEvent(ctx, eventId) {
        const data = await ctx.stub.getState(eventId);
        if (!data || data.length === 0) {
            throw new Error(`Event/Certificate not found: ${eventId}`);
        }
        return data.toString();
    }


    /** Return full history of an event key (all versions) */
    async getEventHistory(ctx, eventId) {
        const iterator = await ctx.stub.getHistoryForKey(eventId);
        const history = [];

        while (true) {
            const res = await iterator.next();
            if (res.done) break;
            const { txId, timestamp: ts, isDelete, value } = res.value;
            history.push({
                txId,
                isDelete,
                timestamp: new Date(ts.seconds.low * 1000).toISOString(),
                value: isDelete ? null : JSON.parse(value.toString()),
            });
        }

        await iterator.close();
        return JSON.stringify(history);
    }


    /**
     * Query all events for a specific field ID using composite key index.
     * Returns an array of farm events ordered by ledger insertion.
     */
    async getEventsByField(ctx, fieldId) {
        const iterator = await ctx.stub.getStateByPartialCompositeKey(IDX_FIELD, [fieldId]);
        const results = [];

        while (true) {
            const res = await iterator.next();
            if (res.done) break;

            // Composite key gives us the event/cert ID — fetch the full record
            const { attributes } = ctx.stub.splitCompositeKey(res.value.key);
            const eventId = attributes[1];
            const eventBytes = await ctx.stub.getState(eventId);
            if (eventBytes && eventBytes.length > 0) {
                results.push(JSON.parse(eventBytes.toString()));
            }
        }

        await iterator.close();
        return JSON.stringify(results);
    }


    /**
     * Rich query (CouchDB only — requires CouchDB peer state database).
     * Finds all disease alerts with severity = "critical".
     */
    async getCriticalAlerts(ctx) {
        const query = {
            selector: {
                docType: "FarmEvent",
                eventType: EventType.DISEASE_ALERT,
                "data.severity": "critical",
            },
            sort: [{ timestamp: "desc" }],
            limit: 50,
        };
        return _richQuery(ctx, query);
    }


    /**
     * Rich query: get all certificates for a specific crop type.
     */
    async getCertsByBatch(ctx, batchId) {
        const query = {
            selector: {
                docType: "NutraCertificate",
                batchId,
            },
        };
        return _richQuery(ctx, query);
    }

}


// ──────────────────────────────────────────────
// PRIVATE HELPERS
// ──────────────────────────────────────────────

/**
 * Authorization guard — checks that the invoking MSP is in allowedMSPs.
 * In production, supplement with attribute-based access control (ABAC).
 */
function _requireRole(ctx, allowedMSPs) {
    const mspId = ctx.clientIdentity.getMSPID();
    if (!allowedMSPs.includes(mspId)) {
        throw new Error(
            `Access denied: MSP '${mspId}' is not authorized. Allowed: ${allowedMSPs.join(", ")}`
        );
    }
}

/** Safe number parser — throws on NaN */
function _parseNum(val) {
    const n = parseFloat(val);
    if (isNaN(n)) throw new Error(`Invalid numeric value: '${val}'`);
    return n;
}

/** Execute a CouchDB rich query and collect results */
async function _richQuery(ctx, queryObj) {
    const iterator = await ctx.stub.getQueryResult(JSON.stringify(queryObj));
    const results = [];

    while (true) {
        const res = await iterator.next();
        if (res.done) break;
        results.push(JSON.parse(res.value.value.toString()));
    }

    await iterator.close();
    return JSON.stringify(results);
}


// ──────────────────────────────────────────────
// EXPORT
// ──────────────────────────────────────────────
module.exports = FarmEventContract;
