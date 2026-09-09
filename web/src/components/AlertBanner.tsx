import type { RiskPredictionResponse } from "../lib/types";
import { AlertTriangleIcon } from "./icons";

/**
 * VigilAI-style critical strip shown above the dashboard when the latest risk
 * evaluation is ELEVATED or HIGH_ATTENTION. Nothing renders for LOW / no data.
 */
export function AlertBanner({ risk }: { risk: RiskPredictionResponse | null }) {
  if (!risk || risk.risk_level === "LOW") return null;

  const high = risk.risk_level === "HIGH_ATTENTION";
  const triggered = risk.explanations.filter((e) => e.triggered).map((e) => e.detail);

  const title = high ? "High attention — check on the person" : "Elevated readings detected";
  const fallback = high
    ? "The latest reading is outside the safe range. Contact a caregiver or clinician if this persists."
    : "Some vitals are drifting from the usual baseline. Keep an eye on the trend below.";

  return (
    <div className={`alert-banner${high ? "" : " alert-banner--warn"}`} role="alert">
      <AlertTriangleIcon width={18} height={18} />
      <div className="alert-banner__body">
        <span className="alert-banner__title">{title}</span>
        <span className="alert-banner__text">
          {triggered.length ? triggered.join(" · ") : fallback}
        </span>
      </div>
    </div>
  );
}
