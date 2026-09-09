/**
 * Live Monitor — real-time view of the IoT wearable.
 *
 * Data source: the Firebase Realtime Database the ESP32 writes to (see
 * lib/firebase.ts). This is independent of the backend-driven Dashboard.
 *
 *  - Live vitals cards (heart rate / SpO2 / temperature / pressure)
 *  - A streaming line chart with warning + danger reference bands
 *  - Fall-detection alert: red banner + attention tone + desktop notification
 *  - GPS location on an embedded map
 *  - "Sync to my health record" — pushes the current reading through the
 *    backend ingest pipeline so it feeds the ML risk engine and history
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useLiveVitals } from "../hooks/useLiveVitals";
import type { LiveVitals } from "../lib/firebase";
import {
  notificationPermission,
  playAlarm,
  requestNotificationPermission,
  sendNotification,
  type NotifyPermission,
} from "../lib/alerts";
import { ApiError, api } from "../lib/api";
import {
  ActivityIcon,
  AlertTriangleIcon,
  DropletIcon,
  HeartPulseIcon,
  ThermometerIcon,
} from "../components/icons";

type MetricKey = "heartRateBpm" | "spo2Percent" | "bodyTempC" | "pressureHpa";

interface MetricSpec {
  key: MetricKey;
  label: string;
  unit: string;
  decimals: number;
  color: string;
  Icon: typeof HeartPulseIcon;
  domain: [number, number];
  warn: [number, number];
  danger: [number, number];
}

const METRICS: MetricSpec[] = [
  { key: "heartRateBpm", label: "Heart rate", unit: "bpm", decimals: 0, color: "var(--hr)", Icon: HeartPulseIcon, domain: [40, 180], warn: [50, 120], danger: [40, 150] },
  { key: "spo2Percent", label: "SpO₂", unit: "%", decimals: 0, color: "var(--spo2)", Icon: DropletIcon, domain: [80, 100], warn: [92, 100], danger: [88, 100] },
  { key: "bodyTempC", label: "Temperature", unit: "°C", decimals: 1, color: "var(--temp)", Icon: ThermometerIcon, domain: [34, 41], warn: [35.5, 37.8], danger: [35, 38.5] },
  { key: "pressureHpa", label: "Pressure", unit: "hPa", decimals: 0, color: "var(--sleep)", Icon: ActivityIcon, domain: [980, 1040], warn: [990, 1025], danger: [985, 1030] },
];

const fmtClock = (t: number) =>
  new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function severity(spec: MetricSpec, value: number | null): "ok" | "warn" | "danger" {
  if (value == null) return "ok";
  if (value < spec.danger[0] || value > spec.danger[1]) return "danger";
  if (value < spec.warn[0] || value > spec.warn[1]) return "warn";
  return "ok";
}

export function LiveMonitor() {
  const { latest, history, status, error, paused, setPaused, fallStartedAt } = useLiveVitals(60);
  const [metric, setMetric] = useState<MetricKey>("heartRateBpm");
  const spec = METRICS.find((m) => m.key === metric) ?? METRICS[0];

  return (
    <div className="dashboard">
      <header className="dashboard__header">
        <div>
          <h1>Live monitor</h1>
          <p className="dashboard__sub">
            Real-time feed from the wearable
            {latest ? ` · updated ${fmtClock(latest.receivedAt)}` : ""}
          </p>
        </div>
        <div className="dashboard__actions">
          <ConnBadge status={status} paused={paused} />
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setPaused(!paused)}
            disabled={status === "error"}
          >
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </header>

      <FallAlert startedAt={fallStartedAt} latest={latest} />

      {error && (
        <p className="dashboard__error" role="alert">
          {error}
        </p>
      )}

      {!latest && status !== "error" && (
        <p className="dashboard__sub">Waiting for the first reading from the device…</p>
      )}

      {latest && (
        <div className="vitals">
          {METRICS.map((m) => {
            const value = latest[m.key];
            const sev = severity(m, value);
            return (
              <div
                className={`stat${sev === "ok" ? "" : ` stat--${sev}`}`}
                key={m.key}
                style={{ "--metric": m.color } as unknown as CSSProperties}
              >
                <div className="stat__top">
                  <span className="stat__icon">
                    <m.Icon width={16} height={16} />
                  </span>
                  {m.label}
                </div>
                <div className="stat__value">
                  {value != null ? value.toFixed(m.decimals) : "—"}
                  {value != null && <small>{m.unit}</small>}
                </div>
                <div className="stat__delta">
                  {sev === "danger" ? "outside safe range" : sev === "warn" ? "borderline" : "in range"}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="dashboard__layout">
        <div className="dashboard__charts">
          <section className="card chart-card">
            <header className="chart-card__header">
              <h3>
                {spec.label} <span className="chart-card__unit">{spec.unit}</span>
              </h3>
              <div className="seg" role="tablist" aria-label="Chart metric">
                {METRICS.map((m) => (
                  <button
                    key={m.key}
                    role="tab"
                    aria-selected={m.key === metric}
                    className={`seg__btn${m.key === metric ? " seg__btn--active" : ""}`}
                    onClick={() => setMetric(m.key)}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </header>
            <div className="chart-card__body">
              {history.length < 2 ? (
                <div className="chart-card__placeholder">Collecting live data…</div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={history} margin={{ top: 10, right: 14, bottom: 0, left: -14 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis
                      dataKey="receivedAt"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      scale="time"
                      tickFormatter={fmtClock}
                      stroke="var(--text-muted)"
                      fontSize={11}
                      minTickGap={40}
                    />
                    <YAxis
                      domain={spec.domain}
                      stroke="var(--text-muted)"
                      fontSize={11}
                      width={40}
                      allowDecimals={spec.decimals > 0}
                    />
                    <Tooltip
                      labelFormatter={(t) => fmtClock(Number(t))}
                      formatter={(value) => [`${Number(value).toFixed(spec.decimals)} ${spec.unit}`, spec.label]}
                      contentStyle={{
                        background: "var(--surface)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                    <ReferenceArea y1={spec.domain[0]} y2={spec.danger[0]} fill="var(--risk-high)" fillOpacity={0.06} stroke="none" />
                    <ReferenceArea y1={spec.danger[1]} y2={spec.domain[1]} fill="var(--risk-high)" fillOpacity={0.06} stroke="none" />
                    <ReferenceArea y1={spec.warn[0]} y2={spec.warn[1]} fill={spec.color} fillOpacity={0.07} stroke="none" />
                    <Line
                      type="monotone"
                      dataKey={metric}
                      name={spec.label}
                      stroke={spec.color}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>

          <LocationCard latest={latest} />
        </div>

        <aside className="dashboard__side">
          <SyncPanel latest={latest} />
          <CompassCard latest={latest} />
        </aside>
      </div>
    </div>
  );
}

// --- connection badge -------------------------------------------------

function ConnBadge({ status, paused }: { status: string; paused: boolean }) {
  const label = paused ? "Paused" : status === "live" ? "Live" : status === "error" ? "Offline" : "Connecting…";
  const mod = paused ? "elevated" : status === "live" ? "low" : status === "error" ? "high" : "unknown";
  return (
    <span className={`risk-badge risk-badge--${mod}`}>
      <span className="risk-badge__dot" aria-hidden="true" />
      {label}
    </span>
  );
}

// --- fall alert -----------------------------------------------------

function FallAlert({ startedAt, latest }: { startedAt: number | null; latest: LiveVitals | null }) {
  const [perm, setPerm] = useState<NotifyPermission>(() => notificationPermission());
  const firedFor = useRef<number | null>(null);

  useEffect(() => {
    if (startedAt == null || firedFor.current === startedAt) return;
    firedFor.current = startedAt;
    playAlarm();
    sendNotification("Fall detected", "The wearable reported a possible fall. Check on the person.");
  }, [startedAt]);

  if (startedAt == null) {
    if (perm === "default") {
      return (
        <div className="alert-banner alert-banner--warn" role="status">
          <AlertTriangleIcon width={18} height={18} />
          <div className="alert-banner__body">
            <span className="alert-banner__title">Enable fall alerts</span>
            <span className="alert-banner__text">
              Allow notifications to be alerted even when this tab is in the background.{" "}
              <button
                className="linklike"
                onClick={async () => setPerm(await requestNotificationPermission())}
              >
                Enable
              </button>
            </span>
          </div>
        </div>
      );
    }
    return null;
  }

  return (
    <div className="alert-banner" role="alert">
      <AlertTriangleIcon width={18} height={18} />
      <div className="alert-banner__body">
        <span className="alert-banner__title">Fall detected</span>
        <span className="alert-banner__text">
          Reported {new Date(startedAt).toLocaleTimeString()}. Status:{" "}
          {latest?.status || "unknown"}. Contact a caregiver if the person does not respond.{" "}
          <button className="linklike" onClick={playAlarm}>
            Replay tone
          </button>
        </span>
      </div>
    </div>
  );
}

// --- sync to backend ------------------------------------------------

function SyncPanel({ latest }: { latest: LiveVitals | null }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [auto, setAuto] = useState(false);

  const canSync =
    latest != null &&
    (latest.heartRateBpm != null || latest.spo2Percent != null || latest.bodyTempC != null);

  const sync = useCallback(async () => {
    if (!latest) return;
    setBusy(true);
    setMsg(null);
    const reading: Record<string, number> = {};
    if (latest.heartRateBpm != null) reading.heart_rate_bpm = latest.heartRateBpm;
    if (latest.spo2Percent != null) reading.spo2_percent = latest.spo2Percent;
    if (latest.bodyTempC != null) reading.body_temp_c = latest.bodyTempC;
    try {
      await api.ingestReading(reading);
      setMsg(`Synced at ${new Date().toLocaleTimeString()}`);
    } catch (err) {
      setMsg(err instanceof ApiError ? err.detail : "Sync failed — is the backend running?");
    } finally {
      setBusy(false);
    }
  }, [latest]);

  const latestRef = useRef(latest);
  latestRef.current = latest;
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => {
      if (latestRef.current) void sync();
    }, 60_000);
    return () => clearInterval(id);
  }, [auto, sync]);

  return (
    <section className="card">
      <div className="risk-panel__header">
        <h2>Sync to health record</h2>
      </div>
      <p className="dashboard__sub" style={{ marginTop: 0 }}>
        Push the current live reading through the backend so it feeds your risk score,
        trend charts and AI companion.
      </p>
      <button className="btn btn--block" onClick={() => void sync()} disabled={!canSync || busy}>
        {busy ? "Syncing…" : "Sync current reading"}
      </button>
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 13 }}>
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
        Auto-sync every 60s
      </label>
      {msg && <p className="risk-panel__foot" style={{ marginTop: 8 }}>{msg}</p>}
    </section>
  );
}

// --- compass / accelerometer --------------------------------------

function CompassCard({ latest }: { latest: LiveVitals | null }) {
  if (!latest) return null;
  const { x, y, z } = latest.compass;
  return (
    <section className="card">
      <div className="risk-panel__header">
        <h2>Motion (accelerometer)</h2>
      </div>
      <div className="kv">
        <div><span>X</span><b>{x.toFixed(2)}</b></div>
        <div><span>Y</span><b>{y.toFixed(2)}</b></div>
        <div><span>Z</span><b>{z.toFixed(2)}</b></div>
      </div>
    </section>
  );
}

// --- location ------------------------------------------------------

function LocationCard({ latest }: { latest: LiveVitals | null }) {
  const coords = useMemo(() => {
    if (!latest || latest.lat == null || latest.lng == null) return null;
    if (latest.lat === 0 && latest.lng === 0) return null;
    return { lat: latest.lat, lng: latest.lng };
  }, [latest]);

  return (
    <section className="card chart-card">
      <header className="chart-card__header">
        <h3>Location</h3>
        {coords && (
          <a
            className="chart-card__unit linklike"
            href={`https://www.openstreetmap.org/?mlat=${coords.lat}&mlon=${coords.lng}#map=16/${coords.lat}/${coords.lng}`}
            target="_blank"
            rel="noreferrer"
          >
            open full map
          </a>
        )}
      </header>
      {!coords ? (
        <div className="chart-card__placeholder">No GPS fix from the device yet.</div>
      ) : (
        <>
          <iframe
            title="Device location"
            className="map-frame"
            loading="lazy"
            referrerPolicy="no-referrer"
            src={
              `https://www.openstreetmap.org/export/embed.html?bbox=${coords.lng - 0.008}%2C${
                coords.lat - 0.006
              }%2C${coords.lng + 0.008}%2C${coords.lat + 0.006}&layer=mapnik&marker=${coords.lat}%2C${coords.lng}`
            }
          />
          <p className="chart-card__meta">
            <span>lat {coords.lat.toFixed(5)}</span>
            <span>lng {coords.lng.toFixed(5)}</span>
          </p>
        </>
      )}
    </section>
  );
}
