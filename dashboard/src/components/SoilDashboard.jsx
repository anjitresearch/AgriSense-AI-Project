import React, { useState, useEffect, useCallback } from "react";
import {
    LineChart, Line, BarChart, Bar,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend,
    ResponsiveContainer, RadialBarChart, RadialBar, PolarAngleAxis
} from "recharts";

// ──────────────────────────────────────────────
// CONFIGURATION
// ──────────────────────────────────────────────
const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:9001";
const MAX_HISTORY = 60; // Max data points on line chart

export default function SoilDashboard() {
    const [activeFarm, setActiveFarm] = useState("farm001");
    const [soilData, setSoilData] = useState(null);
    const [history, setHistory] = useState([]);
    const [wsStatus, setWsStatus] = useState("connecting");
    const [alerts, setAlerts] = useState([]);

    // Mock initial data if WS fails (simulated 24-h history)
    useEffect(() => {
        const mockHist = Array.from({ length: 24 }).map((_, i) => ({
            time: `${i}:00`,
            pH: +(6.0 + Math.random() * 1.5).toFixed(2),
            moisture: +(30 + Math.random() * 40).toFixed(1),
            EC: Math.floor(200 + Math.random() * 500)
        }));
        setHistory(mockHist);
    }, []);

    // ── WebSocket Connection ─────────────────────────────────
    useEffect(() => {
        const ws = new WebSocket(WS_URL);

        ws.onopen = () => setWsStatus("live");
        ws.onerror = () => setWsStatus("error");
        ws.onclose = () => setWsStatus("error");

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                // Expecting topic matching 'agrisense/farm001/soil'
                if (msg.topic && msg.topic.startsWith("agrisense/") && msg.topic.endsWith("/soil")) {
                    const farmId = msg.topic.split("/")[1];
                    if (farmId === activeFarm) {
                        handleNewReading(msg.payload);
                    }
                } else if (!msg.topic && msg.device_id) {
                    // Direct payload fallback
                    handleNewReading(msg);
                }
            } catch (err) {
                console.error("WebSocket message parse error", err);
            }
        };

        return () => ws.close();
    }, [activeFarm]);

    const handleNewReading = useCallback((payload) => {
        setSoilData(payload);

        // Process Alerts
        const newAlerts = [];
        if (payload.pH < 5.5 || payload.pH > 8.0) newAlerts.push({ level: "critical", msg: `pH Out of bounds: ${payload.pH}` });
        if (payload.moisture < 20) newAlerts.push({ level: "critical", msg: `Low moisture: ${payload.moisture}%` });
        if (payload.npk.N < 50 || payload.npk.P < 20 || payload.npk.K < 30) {
            newAlerts.push({ level: "warning", msg: "Low NPK levels detected" });
        }
        setAlerts(newAlerts);

        // Update History
        setHistory(prev => {
            const d = new Date(payload.timestamp || Date.now());
            const newPt = {
                time: `${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`,
                pH: payload.pH,
                moisture: payload.moisture,
                EC: payload.EC
            };
            return [...prev.slice(-(MAX_HISTORY - 1)), newPt];
        });
    }, []);

    // ── CSV Export ──────────────────────────────────────────
    const exportCSV = () => {
        const headers = ["Time", "pH", "Moisture_%", "EC_uS/cm\n"];
        const csvContent = "data:text/csv;charset=utf-8,"
            + headers.join(",")
            + history.map(row => `${row.time},${row.pH},${row.moisture},${row.EC}`).join("\n");

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `soil_history_${activeFarm}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    // ── Get Global Alert Status ─────────────────────────────
    const getBannerStatus = () => {
        if (alerts.some(a => a.level === "critical")) return { text: "CRITICAL ALERTS", color: "var(--red-400)", bg: "rgba(231,76,60,0.15)" };
        if (alerts.some(a => a.level === "warning")) return { text: "WARNING", color: "var(--amber-400)", bg: "rgba(243,156,18,0.15)" };
        return { text: "SYSTEM OPTIMAL", color: "var(--green-400)", bg: "rgba(46,204,113,0.15)" };
    };

    const banner = getBannerStatus();

    // ── Gauge Chart Helper ──────────────────────────────────
    const Gauge = ({ value, min, max, name, color, unit }) => {
        const percentage = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
        return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', background: 'var(--bg-surface)', padding: '16px', borderRadius: '12px' }}>
                <h4 style={{ color: 'var(--text-secondary)', marginBottom: '-20px', zIndex: 1 }}>{name}</h4>
                <ResponsiveContainer width={150} height={150}>
                    <RadialBarChart
                        cx="50%" cy="50%"
                        innerRadius="70%" outerRadius="100%"
                        barSize={10} data={[{ name, value: percentage, fill: color }]}
                        startAngle={180} endAngle={0}
                    >
                        <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
                        <RadialBar background clockWise dataKey="value" cornerRadius={5} />
                    </RadialBarChart>
                </ResponsiveContainer>
                <div style={{ marginTop: '-40px', fontSize: '24px', fontWeight: 'bold', color: 'var(--text-primary)' }}>
                    {value ?? '--'}<span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{unit}</span>
                </div>
            </div>
        );
    };

    return (
        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

            {/* HEADER SECTION */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        🪨 TERRA-NODE™ Soil Health
                        <span style={{ fontSize: 12, padding: '4px 8px', borderRadius: 12, background: wsStatus === 'live' ? 'rgba(46,204,113,0.2)' : 'rgba(231,76,60,0.2)', color: wsStatus === 'live' ? 'var(--green-400)' : 'var(--red-400)' }}>
                            {wsStatus.toUpperCase()}
                        </span>
                    </h2>
                    <p style={{ color: 'var(--text-muted)' }}>Real-time telemetry and 24-h historical trends</p>
                </div>

                <div style={{ display: 'flex', gap: '12px' }}>
                    <select
                        value={activeFarm}
                        onChange={e => setActiveFarm(e.target.value)}
                        style={{ padding: '8px 12px', background: 'var(--bg-input)', color: 'var(--text-primary)', border: '1px solid var(--bg-border)', borderRadius: '6px' }}
                    >
                        <option value="farm001">Farm 001 (Main)</option>
                        <option value="farm002">Farm 002 (North)</option>
                        <option value="farm003">Farm 003 (Greenhouse)</option>
                    </select>
                    <button
                        onClick={exportCSV}
                        style={{ padding: '8px 16px', background: 'var(--blue-400)', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
                    >
                        📥 Export CSV
                    </button>
                </div>
            </div>

            {/* ALERT BANNER */}
            <div style={{ padding: '12px 16px', background: banner.bg, borderLeft: `4px solid ${banner.color}`, borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '16px' }}>
                <strong style={{ color: banner.color }}>{banner.text}</strong>
                <div style={{ display: 'flex', gap: '12px' }}>
                    {alerts.map((a, i) => (
                        <span key={i} style={{ color: 'var(--text-primary)', fontSize: '13px' }}>• {a.msg}</span>
                    ))}
                </div>
            </div>

            {/* LIVE GAUGES (Top Row) */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
                <Gauge value={soilData?.pH} min={0} max={14} name="pH Level" color="var(--purple-400)" unit="pH" />
                <Gauge value={soilData?.moisture} min={0} max={100} name="Moisture" color="var(--blue-400)" unit="%" />
                <Gauge value={soilData?.EC} min={0} max={2000} name="Conductivity (EC)" color="var(--amber-400)" unit="µS" />

                {/* NPK Bar Chart mini-panel */}
                <div style={{ background: 'var(--bg-surface)', padding: '16px', borderRadius: '12px', display: 'flex', flexDirection: 'column' }}>
                    <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px', textAlign: 'center' }}>Macronutrients (NPK)</h4>
                    <ResponsiveContainer width="100%" height={120}>
                        <BarChart data={[
                            { name: 'N', val: soilData?.npk?.N || 0, fill: '#3498db' },
                            { name: 'P', val: soilData?.npk?.P || 0, fill: '#e67e22' },
                            { name: 'K', val: soilData?.npk?.K || 0, fill: '#9b59b6' }
                        ]} layout="vertical" margin={{ top: 0, right: 20, left: -20, bottom: 0 }}>
                            <XAxis type="number" hide />
                            <YAxis dataKey="name" type="category" tick={{ fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                            <Tooltip cursor={{ fill: 'var(--bg-card-hover)' }} formatter={(val) => [`${val} mg/kg`, 'Value']} />
                            <Bar dataKey="val" radius={[0, 4, 4, 0]} barSize={15} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* HISTORICAL TRENDLINE */}
            <div style={{ background: 'var(--bg-surface)', padding: '24px', borderRadius: '12px', flex: 1, minHeight: '350px' }}>
                <h3 style={{ color: 'var(--text-primary)', marginBottom: '16px' }}>📈 24-Hour Trend</h3>
                <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={history} margin={{ top: 5, right: 20, left: -10, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                        <XAxis dataKey="time" tick={{ fill: 'var(--text-muted)' }} />
                        <YAxis yAxisId="left" tick={{ fill: 'var(--text-muted)' }} />
                        <YAxis yAxisId="right" orientation="right" tick={{ fill: 'var(--text-muted)' }} />
                        <Tooltip
                            contentStyle={{ background: 'var(--bg-card)', borderColor: 'var(--bg-border)', borderRadius: '8px' }}
                            itemStyle={{ color: 'var(--text-primary)' }}
                        />
                        <Legend />
                        <Line yAxisId="left" type="monotone" dataKey="moisture" stroke="var(--blue-400)" name="Moisture %" strokeWidth={2} dot={false} />
                        <Line yAxisId="right" type="monotone" dataKey="pH" stroke="var(--purple-400)" name="pH" strokeWidth={2} dot={false} />
                        <Line yAxisId="right" type="monotone" dataKey="EC" stroke="var(--amber-400)" name="EC (µS/cm)" strokeWidth={2} dot={false} />
                    </LineChart>
                </ResponsiveContainer>
            </div>

        </div>
    );
}
