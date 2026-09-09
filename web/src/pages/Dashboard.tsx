/**
 * Dashboard — the main authenticated page.
 *
 *  - Heart rate / SpO2 / body-temp trend lines over a 7 / 30 / 90-day range.
 *  - A shaded band + dashed line per chart = the baseline average from
 *    GET /health/trends (moving_average ± a metric-specific margin).
 *  - Current risk badge + triggered-rule list from POST /health/evaluate.
 *  - CSV export of the shown readings; the AI companion chat in the sidebar.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AIChat } from "../components/AIChat";
import { AlertBanner } from "../components/AlertBanner";
import { RiskBadge } from "../components/RiskBadge";
import { VitalsGrid } from "../components/VitalsGrid";
import { RefreshIcon } from "../components/icons";
import { ApiError, api } from "../lib/api";
import { downloadText, entriesToCsv } from "../lib/csv";
import type {
  HealthEntry,
  MetricTrend,
  RiskPredictionResponse,
  TrendsResponse,
} from "../lib/types";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
] as const;

type VitalKey = "heart_rate_bpm" | "spo2_percent" | "body_temp_c";

interface VitalConfig {
  key: VitalKey;
  label: string;
  unit: string;
  color: string;
  yDomain: [number, number];
  /** half-width of the baseline band, as a fraction of the 7-day average */
  bandPct: number;
  decimals: number;
}

const VITALS: VitalConfig[] = [
  { key: "heart_rate_bpm", label: "Heart rate", unit: "bpm", color: "#e11d48", yDomain: [40, 140], bandPct: 0.08, decimals: 0 },
  { key: "spo2_percent", label: "SpO₂", unit: "%", color: "#2563eb", yDomain: [86, 100], bandPct: 0.02, decimals: 0 },
  { key: "body_temp_c", label: "Body temperature", unit: "°C", color: "#d97706", yDomain: [35, 40], bandPct: 0.015, decimals: 1 },
];

interface ChartPoint {
  t: number; // epoch ms — numeric X so gaps are spaced by real time
  heart_rate_bpm: number | null;
  spo2_percent: number | null;
  body_temp_c: number | null;
}

function toPoints(entries: HealthEntry[]): ChartPoint[] {
  return entries
    .map((e) => ({
      t: new Date(e.recorded_at).getTime(),
      heart_rate_bpm: e.heart_rate_bpm,
      spo2_percent: e.spo2_percent,
      body_temp_c: e.body_temp_c,
    }))
    .sort((a, b) => a.t - b.t);
}

const fmtDay = (t: number) =>
  new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const fmtDateTime = (t: number) =>
  new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export function Dashboard() {
  const [entries, setEntries] = useState<HealthEntry[]>([]);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [risk, setRisk] = useState<RiskPredictionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<number>(7);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [entriesRes, trendsRes, riskRes] = await Promise.allSettled([
      api.getEntries(days, days >= 90 ? 2000 : 1000),
      api.getTrends(days <= 7 ? "7d" : "30d"),
      api.evaluateLatest(),
    ]);

    if (entriesRes.status === "fulfilled") setEntries(entriesRes.value);
    if (trendsRes.status === "fulfilled") setTrends(trendsRes.value);

    if (riskRes.status === "fulfilled") {
      setRisk(riskRes.value);
    } else if (riskRes.reason instanceof ApiError && riskRes.reason.status === 404) {
      setRisk(null); // no readings yet — not an error
    }

    if (entriesRes.status === "rejected") {
      setError(
        entriesRes.reason instanceof ApiError
          ? entriesRes.reason.detail
          : "Couldn't load your health data.",
      );
    }
    setLoading(false);
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const points = useMemo(() => toPoints(entries), [entries]);

  const baselineFor = useMemo(() => {
    const map = new Map<string, MetricTrend>();
    trends?.metrics.forEach((m) => map.set(m.metric, m));
    return (key: string) => map.get(key) ?? null;
  }, [trends]);

  const firstLoad = loading && entries.length === 0;

  return (
    <div className="dashboard">
      <header className="dashboard__header">
        <div>
          <h1>Health dashboard</h1>
          <p className="dashboard__sub">
            {`Last ${days} days`}
            {trends ? ` · updated ${fmtDateTime(new Date(trends.generated_at).getTime())}` : ""}
            {entries.length ? ` · ${entries.length} readings` : ""}
          </p>
        </div>
        <div className="dashboard__actions">
          {risk ? (
            <RiskBadge level={risk.risk_level} score={risk.risk_score} />
          ) : (
            <span className="risk-badge risk-badge--unknown">
              <span className="risk-badge__dot" aria-hidden="true" />
              No recent reading
            </span>
          )}
          <div className="seg" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r.days}
                className={`seg__btn${days === r.days ? " seg__btn--active" : ""}`}
                onClick={() => setDays(r.days)}
                disabled={loading}
              >
                {r.label}
              </button>
            ))}
          </div>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => downloadText(`health-entries-${days}d.csv`, entriesToCsv(entries))}
            disabled={!entries.length}
            title="Export the shown readings as CSV"
          >
            Export CSV
          </button>
          <button className="btn btn--ghost btn--sm" onClick={() => void load()} disabled={loading}>
            <RefreshIcon width={15} height={15} />
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <AlertBanner risk={risk} />

      {error && (
        <p className="dashboard__error" role="alert">
          {error}
        </p>
      )}

      <VitalsGrid entries={entries} trends={trends} />

      <div className="dashboard__layout">
        <div className="dashboard__charts">
          {VITALS.map((cfg) => (
            <VitalTrendChart
              key={cfg.key}
              config={cfg}
              data={points}
              baseline={baselineFor(cfg.key)}
              loading={firstLoad}
            />
          ))}
        </div>

        <aside className="dashboard__side">
          {risk && <RiskPanel risk={risk} />}
          <AIChat />
        </aside>
      </div>
    </div>
  );
}

// --- one chart ---------------------------------------------------------

function VitalTrendChart({
  config,
  data,
  baseline,
  loading,
}: {
  config: VitalConfig;
  data: ChartPoint[];
  baseline: MetricTrend | null;
  loading: boolean;
}) {
  const avg = baseline?.moving_average ?? null;
  const band =
    avg != null ? { lo: avg * (1 - config.bandPct), hi: avg * (1 + config.bandPct) } : null;
  const deviation = baseline?.baseline_deviation_percent ?? null;
  const latest = baseline?.latest_value ?? null;
  const hasData = data.some((d) => d[config.key] != null);

  return (
    <section className="card chart-card">
      <header className="chart-card__header">
        <h3>
          {config.label} <span className="chart-card__unit">{config.unit}</span>
        </h3>
        <div className="chart-card__meta">
          {latest != null && <span>latest {latest.toFixed(config.decimals)}</span>}
          {avg != null && <span>baseline avg {avg.toFixed(config.decimals)}</span>}
          {deviation != null && (
            <span className={`delta ${deviation >= 0 ? "delta--up" : "delta--down"}`}>
              {deviation >= 0 ? "▲" : "▼"} {Math.abs(deviation).toFixed(1)}%
            </span>
          )}
        </div>
      </header>

      <div className="chart-card__body">
        {loading ? (
          <div className="chart-card__placeholder">Loading…</div>
        ) : !hasData ? (
          <div className="chart-card__placeholder">
            No {config.label.toLowerCase()} readings in the last 7 days.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={224}>
            <LineChart data={data} margin={{ top: 10, right: 14, bottom: 0, left: -14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={fmtDay}
                stroke="var(--text-muted)"
                fontSize={11}
                minTickGap={28}
              />
              <YAxis
                domain={config.yDomain}
                stroke="var(--text-muted)"
                fontSize={11}
                width={40}
                allowDecimals={config.decimals > 0}
              />
              <Tooltip
                labelFormatter={(t) => fmtDateTime(Number(t))}
                formatter={(value) => [
                  `${Number(value).toFixed(config.decimals)} ${config.unit}`,
                  config.label,
                ]}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />

              {/* 7-day baseline comparison band + centre line */}
              {band && (
                <ReferenceArea
                  y1={band.lo}
                  y2={band.hi}
                  fill={config.color}
                  fillOpacity={0.1}
                  stroke="none"
                  ifOverflow="extendDomain"
                />
              )}
              {avg != null && (
                <ReferenceLine
                  y={avg}
                  stroke={config.color}
                  strokeOpacity={0.55}
                  strokeDasharray="5 4"
                  label={{
                    value: "baseline",
                    position: "insideTopRight",
                    fontSize: 10,
                    fill: "var(--text-muted)",
                  }}
                />
              )}

              <Line
                type="monotone"
                dataKey={config.key}
                name={config.label}
                stroke={config.color}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

// --- risk sidebar panel ----------------------------------------------

function RiskPanel({ risk }: { risk: RiskPredictionResponse }) {
  const triggered = risk.explanations.filter((e) => e.triggered);
  return (
    <section className="card risk-panel">
      <header className="risk-panel__header">
        <h2>Current risk</h2>
        <RiskBadge level={risk.risk_level} score={risk.risk_score} />
      </header>
      <ul className="risk-panel__reasons">
        {triggered.length ? (
          triggered.map((e) => <li key={e.rule}>{e.detail}</li>)
        ) : (
          <li className="risk-panel__ok">No safeguard rules triggered.</li>
        )}
      </ul>
      <p className="risk-panel__foot">
        {risk.ml_available
          ? `Model: ${risk.model_version ?? "trained"}`
          : "Model: heuristic fallback"}
        {risk.safeguard_triggered ? " · safeguard raised the level" : ""}
      </p>
    </section>
  );
}
