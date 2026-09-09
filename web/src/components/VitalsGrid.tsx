import type { CSSProperties } from "react";
import type { HealthEntry, MetricTrend, TrendsResponse } from "../lib/types";
import { DropletIcon, HeartPulseIcon, MoonIcon, ThermometerIcon } from "./icons";

type MetricKey = "heart_rate_bpm" | "spo2_percent" | "body_temp_c" | "sleep_hours";

interface Spec {
  key: MetricKey;
  label: string;
  unit: string;
  decimals: number;
  color: string;
  Icon: typeof HeartPulseIcon;
}

const SPECS: Spec[] = [
  { key: "heart_rate_bpm", label: "Heart rate", unit: "bpm", decimals: 0, color: "var(--hr)", Icon: HeartPulseIcon },
  { key: "spo2_percent", label: "SpO₂", unit: "%", decimals: 0, color: "var(--spo2)", Icon: DropletIcon },
  { key: "body_temp_c", label: "Body temp", unit: "°C", decimals: 1, color: "var(--temp)", Icon: ThermometerIcon },
  { key: "sleep_hours", label: "Sleep", unit: "h", decimals: 1, color: "var(--sleep)", Icon: MoonIcon },
];

/** Newest non-null value for a metric, scanning entries back-to-front. */
function latestFromEntries(entries: HealthEntry[], key: MetricKey): number | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const v = entries[i][key];
    if (v != null) return v;
  }
  return null;
}

export function VitalsGrid({
  entries,
  trends,
}: {
  entries: HealthEntry[];
  trends: TrendsResponse | null;
}) {
  const byMetric = new Map<string, MetricTrend>();
  trends?.metrics.forEach((m) => byMetric.set(m.metric, m));

  return (
    <div className="vitals">
      {SPECS.map(({ key, label, unit, decimals, color, Icon }) => {
        const trend = byMetric.get(key) ?? null;
        const value = trend?.latest_value ?? latestFromEntries(entries, key);
        const avg = trend?.moving_average ?? null;
        const dev = trend?.baseline_deviation_percent ?? null;

        return (
          <div
            className="stat"
            key={key}
            style={{ "--metric": color } as unknown as CSSProperties}
          >
            <div className="stat__top">
              <span className="stat__icon">
                <Icon width={16} height={16} />
              </span>
              {label}
            </div>
            <div className="stat__value">
              {value != null ? value.toFixed(decimals) : "—"}
              {value != null && <small>{unit}</small>}
            </div>
            <div
              className={
                "stat__delta" +
                (dev == null ? "" : dev >= 0 ? " stat__delta--up" : " stat__delta--down")
              }
            >
              {dev != null
                ? `${dev >= 0 ? "▲" : "▼"} ${Math.abs(dev).toFixed(1)}% vs baseline`
                : avg != null
                  ? `baseline avg ${avg.toFixed(decimals)} ${unit}`
                  : "no baseline yet"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
