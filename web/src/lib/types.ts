// Mirrors app/schemas.py on the backend.

export type RiskLevel = "LOW" | "ELEVATED" | "HIGH_ATTENTION";

export interface RuleExplanation {
  rule: string;
  triggered: boolean;
  detail: string;
}

export interface RiskPredictionResponse {
  risk_level: RiskLevel;
  risk_score: number;
  probabilities: Record<string, number>;
  explanations: RuleExplanation[];
  ml_available: boolean;
  model_version: string | null;
  safeguard_triggered: boolean;
  latency_ms: number | null;
}

export interface HealthEntry {
  id: number;
  recorded_at: string; // ISO 8601
  source: string;
  heart_rate_bpm: number | null;
  spo2_percent: number | null;
  body_temp_c: number | null;
  systolic_bp: number | null;
  diastolic_bp: number | null;
  respiratory_rate: number | null;
  steps: number | null;
  sleep_hours: number | null;
  weight_kg: number | null;
}

export type TrendWindow = "7d" | "30d";

export interface MetricTrend {
  metric: string; // e.g. "heart_rate_bpm"
  moving_average: number | null;
  baseline_deviation_percent: number | null;
  latest_value: number | null;
  samples: number;
}

export interface TrendsResponse {
  user_id: number;
  window: TrendWindow;
  generated_at: string;
  metrics: MetricTrend[];
}

export interface AuthToken {
  access_token: string;
  token_type: "bearer";
}

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string | null;
}
