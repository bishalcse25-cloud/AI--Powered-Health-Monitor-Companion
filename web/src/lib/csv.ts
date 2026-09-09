/** Minimal CSV builder + browser download, used to export health entries. */

import type { HealthEntry } from "./types";

const COLUMNS: Array<keyof HealthEntry> = [
  "recorded_at",
  "source",
  "heart_rate_bpm",
  "spo2_percent",
  "body_temp_c",
  "systolic_bp",
  "diastolic_bp",
  "respiratory_rate",
  "steps",
  "sleep_hours",
  "weight_kg",
];

function cell(value: unknown): string {
  if (value == null) return "";
  const s = String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function entriesToCsv(entries: HealthEntry[]): string {
  const header = COLUMNS.join(",");
  const rows = entries.map((e) => COLUMNS.map((c) => cell(e[c])).join(","));
  return [header, ...rows].join("\r\n");
}

/** Trigger a client-side download of `content` as `filename`. */
export function downloadText(filename: string, content: string, mime = "text/csv"): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
