/*
 * ==============================================================
 *  CHAIN-PROOF™ — Farm Traceability Chaincode
 *  Platform: Hyperledger Fabric v2.4 (Node.js)
 *  Purpose: Immutable recording of farm-to-consumer events
 * ==============================================================
 */

'use strict';

const { Contract } = require('fabric-contract-api');
const crypto = require('crypto');

class FarmTraceabilityContract extends Contract {

    /**
     * Helper to enforce idempotency / double-spend protection
     */
    async _eventExists(ctx, eventId) {
        const buffer = await ctx.stub.getState(eventId);
        return (!!buffer && buffer.length > 0);
    }

    /**
     * Helper to generate a deterministic hash for a batch passport
     */
    _generateBatchHash(passportData) {
        const str = JSON.stringify(passportData);
        return crypto.createHash('sha256').update(str).digest('hex');
    }

    /**
     * Initialise the ledger with a dummy setup if needed (optional)
     */
    async initLedger(ctx) {
        console.info('============= START : Initialize Ledger ===========');
        console.info('CHAIN-PROOF™ Ledger Ready');
        console.info('============= END : Initialize Ledger ===========');
    }

    /**
     * Main universal entry point for logging farm events
     * @param {String} eventType - SeedingEvent, SoilEvent, DiseaseEvent, HarvestEvent, ColdChainEvent, CertificationEvent
     * @param {String} payloadStr - JSON stringified payload
     */
    async recordEvent(ctx, eventType, payloadStr) {
        const payload = JSON.parse(payloadStr);
        let eventId = '';
        let batchId = payload.batch_id || payload.farm_id; // Use batch_id if cert/coldchain, else farm_id
        const timestamp = new Date((ctx.stub.getTxTimestamp().seconds.low * 1000)).toISOString();

        // Construct a unique deterministic ID for idempotency checks based on event type
        switch (eventType) {
            case 'SeedingEvent':
                eventId = `SEED_${payload.farm_id}_${payload.seed_batch}`;
                break;
            case 'SoilEvent':
                eventId = `SOIL_${payload.farm_id}_${payload.date}`;
                break;
            case 'DiseaseEvent':
                eventId = `DIS_${payload.farm_id}_${payload.date}_${payload.disease_detected.replace(/\s/g, '')}`;
                break;
            case 'HarvestEvent':
                eventId = `HARV_${payload.farm_id}_${payload.date}`;
                batchId = `BATCH_HARV_${payload.farm_id}_${payload.date}`; // Auto-generate batch ID
                payload.generated_batch_id = batchId;
                break;
            case 'ColdChainEvent':
                eventId = `COLD_${payload.batch_id}_${payload.departure}`;
                break;
            case 'CertificationEvent':
                eventId = `CERT_${payload.batch_id}_${payload.fssai_cert_no}`;
                break;
            default:
                throw new Error(`Invalid eventType: ${eventType}`);
        }

        // Idempotency check: Reject duplicate submissions
        const exists = await this._eventExists(ctx, eventId);
        if (exists) {
            throw new Error(`Event ${eventId} already exists! Duplicate submission rejected.`);
        }

        // Standardise record
        const record = {
            docType: 'FarmEvent',
            eventId: eventId,
            eventType: eventType,
            batchId: batchId,
            timestamp: timestamp,
            data: payload
        };

        await ctx.stub.putState(eventId, Buffer.from(JSON.stringify(record)));

        // Index the event by batchId for easy history retrieval
        const indexName = 'batch~event';
        const batchEventIndexKey = ctx.stub.createCompositeKey(indexName, [batchId, eventId]);
        await ctx.stub.putState(batchEventIndexKey, Buffer.from('\u0000'));

        // Also index by farm_id for farm-level history
        if (payload.farm_id) {
            const farmIndexName = 'farm~event';
            const farmEventIndexKey = ctx.stub.createCompositeKey(farmIndexName, [payload.farm_id, eventId]);
            await ctx.stub.putState(farmEventIndexKey, Buffer.from('\u0000'));
        }

        console.info(`============= Logged ${eventType} : ${eventId} ===========`);
        return JSON.stringify({ success: true, eventId: eventId, batchId: batchId });
    }

    /**
     * Retrieve full timeline of all events for a specific Farm
     */
    async getHistory(ctx, farmId) {
        const farmEventResultsIterator = await ctx.stub.getStateByPartialCompositeKey('farm~event', [farmId]);
        const allResults = [];

        while (true) {
            const responseRange = await farmEventResultsIterator.next();
            if (!responseRange || !responseRange.value || !responseRange.value.key) {
                return JSON.stringify(allResults);
            }
            const objectTypeAndAttributes = ctx.stub.splitCompositeKey(responseRange.value.key);
            const returnedEventId = objectTypeAndAttributes.attributes[1];

            const eventBytes = await ctx.stub.getState(returnedEventId);
            if (eventBytes && eventBytes.length > 0) {
                allResults.push(JSON.parse(eventBytes.toString('utf8')));
            }
            if (responseRange.done) {
                await farmEventResultsIterator.close();
                break;
            }
        }

        // Sort chronologically
        allResults.sort((a, b) => (new Date(a.timestamp) - new Date(b.timestamp)));
        return JSON.stringify(allResults);
    }

    /**
     * Generate complete Digital Passport for a specific Harvest Batch
     */
    async generatePassport(ctx, batchId) {
        // Find all events linked to this batchId
        const batchEventResultsIterator = await ctx.stub.getStateByPartialCompositeKey('batch~event', [batchId]);
        const events = [];

        while (true) {
            const responseRange = await batchEventResultsIterator.next();
            if (!responseRange || !responseRange.value || !responseRange.value.key) {
                break;
            }
            const objectTypeAndAttributes = ctx.stub.splitCompositeKey(responseRange.value.key);
            const returnedEventId = objectTypeAndAttributes.attributes[1];
            const eventBytes = await ctx.stub.getState(returnedEventId);
            if (eventBytes && eventBytes.length > 0) {
                events.push(JSON.parse(eventBytes.toString('utf8')));
            }
            if (responseRange.done) {
                await batchEventResultsIterator.close();
                break;
            }
        }

        if (events.length === 0) {
            throw new Error(`No passport data found for batch ${batchId}`);
        }

        // Structure the Digital Passport
        const passport = {
            batchId: batchId,
            generatedAt: new Date((ctx.stub.getTxTimestamp().seconds.low * 1000)).toISOString(),
            passportHash: '', // To be calculated
            timeline: events.sort((a, b) => (new Date(a.timestamp) - new Date(b.timestamp)))
        };

        // Compute immutable deterministic hash
        passport.passportHash = this._generateBatchHash(passport.timeline);

        return JSON.stringify(passport);
    }

    /**
     * Public verification using the hash encoded in the QR code
     */
    async verifyCertificate(ctx, batchId, providedHash) {
        try {
            const passportBytes = await this.generatePassport(ctx, batchId);
            const passport = JSON.parse(passportBytes);

            const isVerified = (passport.passportHash === providedHash);

            return JSON.stringify({
                verified: isVerified,
                batchId: batchId,
                calculatedHash: passport.passportHash,
                providedHash: providedHash,
                certdetails: isVerified ? passport : null
            });
        } catch (error) {
            return JSON.stringify({
                verified: false,
                error: error.message
            });
        }
    }
}

module.exports = FarmTraceabilityContract;
