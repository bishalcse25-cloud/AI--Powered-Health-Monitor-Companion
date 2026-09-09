import type { RiskLevel } from "../lib/types";

const LABELS: Record<RiskLevel, string> = {
  LOW: "Low",
  ELEVATED: "Elevated",
  HIGH_ATTENTION: "High attention",
};

const MODIFIER: Record<RiskLevel, string> = {
  LOW: "low",
  ELEVATED: "elevated",
  HIGH_ATTENTION: "high",
};

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  return (
    <span className={`risk-badge risk-badge--${MODIFIER[level] ?? "unknown"}`}>
      <span className="risk-badge__dot" aria-hidden="true" />
      {LABELS[level] ?? level}
      {typeof score === "number" && <span className="risk-badge__score">{score.toFixed(2)}</span>}
    </span>
  );
}
