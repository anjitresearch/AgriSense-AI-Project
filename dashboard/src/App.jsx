// ==============================================================
//  AgriSense-AI™ Dashboard — App.jsx
//  Live WebSocket telemetry from MQTT-WS bridge (port 9001)
//  Panels: Soil Sensors | Disease Alerts | Drone Flights |
//          NUTRA-SPEC | CHAIN-PROOF Feed | Historical Charts
// ==============================================================

import { useState, useEffect, useRef, useCallback } from "react";
import {
    LineChart, Line, AreaChart, Area, BarChart, Bar,
    RadarChart, Radar, PolarGrid, PolarAngleAxis,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend,
    ResponsiveContainer,
} from "recharts";

// ──────────────────────────────────────────────
// CONFIG — override via .env for production
// ──────────────────────────────────────────────
const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:9001";
const EDGE_BRAIN_URL = import.meta.env.VITE_EDGE_BRAIN_URL || "http://localhost:8000";
const SKYWATCH_URL = import.meta.env.VITE_SKYWATCH_URL || "http://localhost:3001";
const CHAIN_URL = import.meta.env.VITE_CHAIN_URL || "http://localhost:3002";

// How many historical data points to keep per chart
const MAX_HISTORY = 30;

// ──────────────────────────────────────────────
// MOCK DATA GENERATORS (used when WS unavailable)
// ──────────────────────────────────────────────
const randBetween = (lo, hi) => +(lo + Math.random() * (hi - lo)).toFixed(1);

function mockSoilReading() {
    return {
        timestamp: new Date().toISOString(),
        device_id: "TERRA-001",
        nitrogen: randBetween(80, 250),
        phosphorus: randBetween(20, 80),
        potassium: randBetween(100, 300),
        pH: randBetween(5.5, 8.0),
        EC: randBetween(200, 800),
        moisture: randBetween(20, 80),
        soil_temp: randBetween(18, 34),
    };
}

const DISEASES = ["Healthy", "Healthy", "Healthy", "Leaf_Blight", "Powdery_Mildew", "Rust", "Late_Blight"];
const SEVERITY = {
    Healthy: "none", Leaf_Blight: "high", Powdery_Mildew: "medium",
    Rust: "medium", Late_Blight: "high"
};

function mockDiseaseAlert() {
    const disease = DISEASES[Math.floor(Math.random() * DISEASES.length)];
    return {
        timestamp: new Date().toISOString(),
        ingest_id: `INJ-${Date.now()}`,
        field_id: `FIELD-00${Math.ceil(Math.random() * 3)}`,
        disease,
        confidence: randBetween(72, 98),
        severity: SEVERITY[disease] || "low",
        gps_lat: +(11.0168 + Math.random() * 0.01).toFixed(5),
        gps_lon: +(76.9558 + Math.random() * 0.01).toFixed(5),
    };
}

function mockNutra() {
    return {
        flavonoids_mg: randBetween(10, 80),
        anthocyanins_mg: randBetween(5, 40),
        lycopene_mg: randBetween(8, 45),
        vitamin_c_mg: randBetween(15, 60),
        total_phenols_mg: randBetween(50, 300),
    };
}

function mockDroneFlight() {
    const types = ["rgb", "hyperspectral", "ndvi"];
    return {
        flight_id: `FLT-${Date.now()}`,
        field_id: `FIELD-00${Math.ceil(Math.random() * 3)}`,
        altitude_m: randBetween(20, 50),
        image_type: types[Math.floor(Math.random() * 3)],
        timestamp: new Date().toISOString(),
    };
}

function mockChainEvent() {
    const types = [
        { type: "soil", label: "Soil reading logged", hash: Math.random().toString(16).slice(2, 10) },
        { type: "disease", label: "Disease alert recorded", hash: Math.random().toString(16).slice(2, 10) },
        { type: "cert", label: "NutraCertificate issued", hash: Math.random().toString(16).slice(2, 10) },
        { type: "drone", label: "Drone flight committed", hash: Math.random().toString(16).slice(2, 10) },
    ];
    const ev = types[Math.floor(Math.random() * types.length)];
    return { ...ev, timestamp: new Date().toISOString() };
}

// ──────────────────────────────────────────────
// TIME FORMATTER
// ──────────────────────────────────────────────
const fmtTime = (iso) => {
    const d = new Date(iso);
    return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
};

// ──────────────────────────────────────────────
// CUSTOM TOOLTIP (Recharts)
// ──────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null;
    return (
        <div style={{
            background: "#1a1f2e", border: "1px solid #252a3a",
            borderRadius: 8, padding: "8px 12px", fontSize: 12
        }}>
            <p style={{ color: "#8892a4", marginBottom: 4 }}>{label}</p>
            {payload.map((p, i) => (
                <p key={i} style={{ color: p.color }}>
                    {p.name}: <strong>{typeof p.value === "number" ? p.value.toFixed(1) : p.value}</strong>
                </p>
            ))}
        </div>
    );
}

// ──────────────────────────────────────────────
// SIDEBAR NAV
// ──────────────────────────────────────────────
const NAV = [
    { id: "overview", label: "Overview", icon: "🌿" },
    { id: "soil", label: "Soil Sensors", icon: "🪨" },
    { id: "disease", label: "Disease AI", icon: "🔬" },
    { id: "drone", label: "Drone Flights", icon: "🚁" },
    { id: "nutra", label: "NUTRA-SPEC™", icon: "🧪" },
    { id: "chain", label: "CHAIN-PROOF™", icon: "⛓" },
];

// ──────────────────────────────────────────────
// STAT CARD
// ──────────────────────────────────────────────
function StatCard({ label, value, unit, accent, trend, trendDir }) {
    return (
        <div className={`stat-card ${accent}`}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value ?? "—"}</div>
            <div className="stat-unit">{unit}</div>
            {trend && (
                <div className={`stat-trend ${trendDir}`}>
                    {trendDir === "up" ? "▲" : trendDir === "down" ? "▼" : "—"} {trend}
                </div>
            )}
        </div>
    );
}

// ──────────────────────────────────────────────
// APP ROOT
// ──────────────────────────────────────────────
export default function App() {
    const [activeTab, setActiveTab] = useState("overview");
    const [wsStatus, setWsStatus] = useState("connecting"); // connecting | live | error
    const [soil, setSoil] = useState(mockSoilReading());
    const [soilHistory, setSoilHistory] = useState([]);
    const [alerts, setAlerts] = useState([]);
    const [flights, setFlights] = useState([]);
    const [nutra, setNutra] = useState(mockNutra());
    const [chainEvents, setChainEvents] = useState([]);

    const wsRef = useRef(null);
    const timers = useRef([]);

    // ── WebSocket connection to MQTT-WS bridge ────────────────
    const connectWS = useCallback(() => {
        try {
            const ws = new WebSocket(WS_URL);
            wsRef.current = ws;

            ws.onopen = () => setWsStatus("live");
            ws.onerror = () => setWsStatus("error");
            ws.onclose = () => {
                setWsStatus("error");
                // Reconnect after 5 s
                setTimeout(connectWS, 5000);
            };

            ws.onmessage = (ev) => {
                try {
                    const msg = JSON.parse(ev.data);
                    if (msg.topic === "agrisense/terra/soil") {
                        ingestSoil(msg.payload);
                    } else if (msg.topic === "agrisense/skywatch/disease_alert") {
                        ingestAlert(msg.payload);
                    } else if (msg.topic === "agrisense/skywatch/ingest") {
                        ingestFlight(msg.payload);
                    } else if (msg.topic === "agrisense/chain/event") {
                        ingestChain(msg.payload);
                    }
                } catch (_) { /* ignore malformed */ }
            };
        } catch {
            setWsStatus("error");
        }
    }, []);

    // ── Ingestion helpers ─────────────────────────────────────
    const ingestSoil = (payload) => {
        setSoil(payload);
        setSoilHistory(h => [...h.slice(-(MAX_HISTORY - 1)), {
            time: fmtTime(payload.timestamp),
            N: payload.nitrogen,
            P: payload.phosphorus,
            K: payload.potassium,
            pH: payload.pH,
            EC: payload.EC,
            Moist: payload.moisture,
            Temp: payload.soil_temp,
        }]);
    };

    const ingestAlert = (payload) => setAlerts(a => [payload, ...a].slice(0, 50));
    const ingestFlight = (payload) => setFlights(f => [payload, ...f].slice(0, 20));
    const ingestChain = (payload) => setChainEvents(c => [payload, ...c].slice(0, 40));

    // ── Bootstrap: WS attempt + mock fallback ticker ──────────
    useEffect(() => {
        connectWS();

        // Generate initial history for charts
        const initialHistory = Array.from({ length: 20 }, (_, i) => {
            const r = mockSoilReading();
            r.timestamp = new Date(Date.now() - (20 - i) * 5 * 60 * 1000).toISOString();
            return r;
        });
        initialHistory.forEach(ingestSoil);

        // Seed initial alerts, flights, chain events
        for (let i = 0; i < 5; i++) {
            ingestAlert(mockDiseaseAlert());
            ingestFlight(mockDroneFlight());
            ingestChain(mockChainEvent());
        }

        // Mock data ticker — fires every 5 s, pauses if WS goes live
        const tick = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) return;
            ingestSoil(mockSoilReading());
            if (Math.random() > 0.5) ingestAlert(mockDiseaseAlert());
            if (Math.random() > 0.7) ingestFlight(mockDroneFlight());
            if (Math.random() > 0.4) ingestChain(mockChainEvent());
            setNutra(mockNutra());
        }, 5000);

        timers.current.push(tick);
        return () => {
            timers.current.forEach(clearInterval);
            wsRef.current?.close();
        };
    }, []);

    // ──────────────────────────────────────────────
    // RENDER
    // ──────────────────────────────────────────────
    const wsLabel = { connecting: "Connecting…", live: "Live", error: "Simulated" }[wsStatus];

    return (
        <div className="app-shell">
            {/* ── Topbar ── */}
            <header className="topbar">
                <div className="topbar-brand">
                    🌱 <span>AgriSense</span><span className="accent">-AI™</span>
                </div>
                <div className="topbar-right">
                    <div className={`status-pill ${wsStatus === "live" ? "live" : wsStatus === "error" ? "error" : ""}`}>
                        <span className="dot" /> {wsLabel} Feed
                    </div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {fmtTime(new Date().toISOString())}
                    </div>
                </div>
            </header>

            {/* ── Sidebar ── */}
            <nav className="sidebar">
                <span className="nav-label">Navigation</span>
                {NAV.map(n => (
                    <button
                        key={n.id}
                        className={`nav-item ${activeTab === n.id ? "active" : ""}`}
                        onClick={() => setActiveTab(n.id)}
                        id={`nav-${n.id}`}
                    >
                        {n.icon} {n.label}
                    </button>
                ))}
            </nav>

            {/* ── Main ── */}
            <main className="main-content">
                {/* OVERVIEW */}
                {(activeTab === "overview" || activeTab === "soil") && (
                    <>
                        <div className="section-header">
                            <div className="section-title">🪨 Soil Telemetry <small>TERRA-NODE™ • {soil.device_id}</small></div>
                        </div>

                        <div className="stat-grid">
                            <StatCard label="Nitrogen" value={soil.nitrogen} unit="mg/kg" accent="nitrogen" />
                            <StatCard label="Phosphorus" value={soil.phosphorus} unit="mg/kg" accent="phosphorus" />
                            <StatCard label="Potassium" value={soil.potassium} unit="mg/kg" accent="potassium" />
                            <StatCard label="pH" value={soil.pH} unit="pH" accent="ph" />
                            <StatCard label="EC" value={soil.EC} unit="µS/cm" accent="ec" />
                            <StatCard label="Moisture" value={soil.moisture} unit="%" accent="moisture" />
                            <StatCard label="Soil Temp" value={soil.soil_temp} unit="°C" accent="temp" />
                        </div>

                        {/* NPK History chart */}
                        <div className="chart-grid-2">
                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">📈 NPK Trend <span className="panel-badge live">LIVE</span></span>
                                </div>
                                <ResponsiveContainer width="100%" height={200}>
                                    <AreaChart data={soilHistory} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                                        <defs>
                                            <linearGradient id="gradN" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#3498db" stopOpacity={0.3} />
                                                <stop offset="95%" stopColor="#3498db" stopOpacity={0} />
                                            </linearGradient>
                                            <linearGradient id="gradP" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#e67e22" stopOpacity={0.3} />
                                                <stop offset="95%" stopColor="#e67e22" stopOpacity={0} />
                                            </linearGradient>
                                            <linearGradient id="gradK" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#9b59b6" stopOpacity={0.3} />
                                                <stop offset="95%" stopColor="#9b59b6" stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#252a3a" />
                                        <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#555e72" }} interval="preserveStartEnd" />
                                        <YAxis tick={{ fontSize: 10, fill: "#555e72" }} />
                                        <Tooltip content={<CustomTooltip />} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        <Area type="monotone" dataKey="N" stroke="#3498db" fill="url(#gradN)" strokeWidth={2} dot={false} name="Nitrogen" />
                                        <Area type="monotone" dataKey="P" stroke="#e67e22" fill="url(#gradP)" strokeWidth={2} dot={false} name="Phosphorus" />
                                        <Area type="monotone" dataKey="K" stroke="#9b59b6" fill="url(#gradK)" strokeWidth={2} dot={false} name="Potassium" />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </div>

                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">💧 pH · EC · Moisture <span className="panel-badge live">LIVE</span></span>
                                </div>
                                <ResponsiveContainer width="100%" height={200}>
                                    <LineChart data={soilHistory} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#252a3a" />
                                        <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#555e72" }} interval="preserveStartEnd" />
                                        <YAxis tick={{ fontSize: 10, fill: "#555e72" }} />
                                        <Tooltip content={<CustomTooltip />} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        <Line type="monotone" dataKey="pH" stroke="#1abc9c" strokeWidth={2} dot={false} name="pH" />
                                        <Line type="monotone" dataKey="Moist" stroke="#2980b9" strokeWidth={2} dot={false} name="Moisture %" />
                                        <Line type="monotone" dataKey="Temp" stroke="#e74c3c" strokeWidth={2} dot={false} name="Temp °C" />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </>
                )}

                {/* DISEASE ALERTS */}
                {(activeTab === "overview" || activeTab === "disease") && (
                    <>
                        <div className="section-header">
                            <div className="section-title">🔬 Disease Alerts <small>EDGE-BRAIN™ + SKYWATCH-H™</small></div>
                            <span className="panel-badge">{alerts.length} events</span>
                        </div>

                        <div className="chart-grid-2">
                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">🚨 Recent Alerts</span>
                                    {alerts.some(a => ["high", "critical"].includes(a.severity)) && (
                                        <span className="panel-badge alert">ALERT</span>
                                    )}
                                </div>
                                <div className="alert-list">
                                    {alerts.length === 0 && <div className="empty-state">✅ No alerts yet</div>}
                                    {alerts.map((a, i) => (
                                        <div key={i} className={`alert-item ${a.severity}`}>
                                            <div style={{ flex: 1 }}>
                                                <div className="alert-disease">{a.disease.replace(/_/g, " ")}</div>
                                                <div className="alert-meta">
                                                    {a.field_id} · {fmtTime(a.timestamp)} · {a.confidence?.toFixed(1)}% conf
                                                </div>
                                            </div>
                                            <span className={`severity-chip ${a.severity}`}>{a.severity}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">📊 Disease Distribution</span>
                                </div>
                                <ResponsiveContainer width="100%" height={230}>
                                    <BarChart
                                        data={Object.entries(
                                            alerts.reduce((acc, a) => {
                                                acc[a.disease.replace(/_/g, " ")] = (acc[a.disease.replace(/_/g, " ")] || 0) + 1;
                                                return acc;
                                            }, {})
                                        ).map(([d, c]) => ({ disease: d.length > 12 ? d.slice(0, 12) + "…" : d, count: c }))}
                                        margin={{ top: 4, right: 8, bottom: 40, left: 0 }}
                                    >
                                        <CartesianGrid strokeDasharray="3 3" stroke="#252a3a" />
                                        <XAxis dataKey="disease" tick={{ fontSize: 10, fill: "#555e72" }} angle={-35} textAnchor="end" />
                                        <YAxis tick={{ fontSize: 10, fill: "#555e72" }} allowDecimals={false} />
                                        <Tooltip content={<CustomTooltip />} />
                                        <Bar dataKey="count" fill="#27ae60" radius={[4, 4, 0, 0]} name="Count" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </>
                )}

                {/* DRONE FLIGHTS */}
                {(activeTab === "overview" || activeTab === "drone") && (
                    <>
                        <div className="section-header">
                            <div className="section-title">🚁 Drone Flights <small>SKYWATCH-H™</small></div>
                            <span className="panel-badge">{flights.length} flights</span>
                        </div>

                        <div className="chart-panel">
                            <div className="flight-list">
                                {flights.length === 0 && <div className="empty-state">No flights yet</div>}
                                {flights.map((f, i) => (
                                    <div key={i} className="flight-row">
                                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                            <span className="flight-id">{f.flight_id}</span>
                                            <span className="flight-meta">{f.field_id} · {f.image_type?.toUpperCase()}</span>
                                        </div>
                                        <div style={{ textAlign: "right" }}>
                                            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{f.altitude_m?.toFixed(0)} m</div>
                                            <div className="flight-meta">{fmtTime(f.timestamp)}</div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </>
                )}

                {/* NUTRA-SPEC */}
                {(activeTab === "overview" || activeTab === "nutra") && (
                    <>
                        <div className="section-header">
                            <div className="section-title">🧪 Phytochemical Analysis <small>NUTRA-SPEC™ · PLSR Model</small></div>
                        </div>

                        <div className="chart-grid-2">
                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">Latest NIR Scan</span>
                                </div>
                                <div className="nutra-grid">
                                    {[
                                        { label: "Flavonoids", key: "flavonoids_mg", color: "#2ecc71", max: 80 },
                                        { label: "Anthocyanins", key: "anthocyanins_mg", color: "#9b59b6", max: 40 },
                                        { label: "Lycopene", key: "lycopene_mg", color: "#e74c3c", max: 45 },
                                        { label: "Vitamin C", key: "vitamin_c_mg", color: "#f39c12", max: 60 },
                                        { label: "Total Phenols", key: "total_phenols_mg", color: "#3498db", max: 300 },
                                    ].map(({ label, key, color, max }) => (
                                        <div key={key} className="nutra-row">
                                            <span className="nutra-label">{label}</span>
                                            <div className="nutra-bar-bg">
                                                <div
                                                    className="nutra-bar-fill"
                                                    style={{ width: `${Math.min(100, ((nutra[key] || 0) / max) * 100)}%`, background: color }}
                                                />
                                            </div>
                                            <span className="nutra-val">{(nutra[key] || 0).toFixed(1)}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="chart-panel">
                                <div className="chart-panel-header">
                                    <span className="chart-panel-title">📡 Radar Profile</span>
                                </div>
                                <ResponsiveContainer width="100%" height={220}>
                                    <RadarChart data={[
                                        { compound: "Flavonoids", value: Math.min(100, ((nutra.flavonoids_mg || 0) / 80) * 100) },
                                        { compound: "Anthocyanins", value: Math.min(100, ((nutra.anthocyanins_mg || 0) / 40) * 100) },
                                        { compound: "Lycopene", value: Math.min(100, ((nutra.lycopene_mg || 0) / 45) * 100) },
                                        { compound: "Vitamin C", value: Math.min(100, ((nutra.vitamin_c_mg || 0) / 60) * 100) },
                                        { compound: "Phenols", value: Math.min(100, ((nutra.total_phenols_mg || 0) / 300) * 100) },
                                    ]}>
                                        <PolarGrid stroke="#252a3a" />
                                        <PolarAngleAxis dataKey="compound" tick={{ fontSize: 11, fill: "#8892a4" }} />
                                        <Radar name="%" dataKey="value" stroke="#2ecc71" fill="#2ecc71" fillOpacity={0.2} />
                                        <Tooltip content={<CustomTooltip />} />
                                    </RadarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </>
                )}

                {/* CHAIN-PROOF FEED */}
                {(activeTab === "overview" || activeTab === "chain") && (
                    <>
                        <div className="section-header">
                            <div className="section-title">⛓ Blockchain Event Feed <small>CHAIN-PROOF™ · Hyperledger Fabric</small></div>
                            <span className="panel-badge">{chainEvents.length} events</span>
                        </div>

                        <div className="chart-panel">
                            <div className="chain-feed">
                                {chainEvents.length === 0 && <div className="empty-state">No events yet</div>}
                                {chainEvents.map((ev, i) => (
                                    <div key={i} className={`chain-event ${ev.type}`}>
                                        <span style={{ opacity: 0.6 }}>{fmtTime(ev.timestamp)}</span>
                                        <span style={{ color: "var(--text-secondary)" }}>{ev.label}</span>
                                        <span className="chain-hash">#{ev.hash}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </>
                )}
            </main>
        </div>
    );
}
