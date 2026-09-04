"""
Deterministic safeguard rules engine.

These rules NEVER depend on the ML model. They exist so that an obviously
dangerous reading (e.g. very low SpO2) always gets flagged, even if:
  - the ML model is offline / not yet trained,
  - the ML model is wrong or under-confident,
  - a sensor sends a value the model has never seen before.

The rules engine always runs, and its result is combined with the ML
result by taking the HIGHEST risk level of the two (see services/ml_engine.py).
"""

from app.schemas import NormalizedHealthRecord, RiskLevel, RuleExplanation

# Each rule: (name, condition function, resulting risk level, message template)
_RULES: list[tuple[str, callable, RiskLevel, str]] = [
    (
        "spo2_critical",
        lambda f: f.spo2_percent is not None and f.spo2_percent < 85,
        RiskLevel.high_attention,
        "SpO2 {value}% is below 85% (severe hypoxemia threshold).",
    ),
    (
        "spo2_low",
        lambda f: f.spo2_percent is not None and 85 <= f.spo2_percent < 90,
        RiskLevel.elevated,
        "SpO2 {value}% is below the normal 90%+ range.",
    ),
    (
        "heart_rate_very_high",
        lambda f: f.heart_rate_bpm is not None and f.heart_rate_bpm > 170,
        RiskLevel.high_attention,
        "Heart rate {value} bpm exceeds 170 bpm.",
    ),
    (
        "heart_rate_very_low",
        lambda f: f.heart_rate_bpm is not None and f.heart_rate_bpm < 35,
        RiskLevel.high_attention,
        "Heart rate {value} bpm is below 35 bpm (severe bradycardia).",
    ),
    (
        "heart_rate_elevated",
        lambda f: f.heart_rate_bpm is not None and 130 <= f.heart_rate_bpm <= 170,
        RiskLevel.elevated,
        "Heart rate {value} bpm is elevated (>=130 bpm).",
    ),
    (
        "body_temp_high",
        lambda f: f.body_temp_c is not None and f.body_temp_c >= 39.5,
        RiskLevel.high_attention,
        "Body temperature {value} C indicates high fever (>=39.5 C).",
    ),
    (
        "body_temp_low",
        lambda f: f.body_temp_c is not None and f.body_temp_c < 35.0,
        RiskLevel.high_attention,
        "Body temperature {value} C indicates hypothermia (<35 C).",
    ),
]

_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.elevated: 1, RiskLevel.high_attention: 2}


def _value_for(field: NormalizedHealthRecord, rule_name: str) -> float | None:
    field_map = {
        "spo2_critical": field.spo2_percent,
        "spo2_low": field.spo2_percent,
        "heart_rate_very_high": field.heart_rate_bpm,
        "heart_rate_very_low": field.heart_rate_bpm,
        "heart_rate_elevated": field.heart_rate_bpm,
        "body_temp_high": field.body_temp_c,
        "body_temp_low": field.body_temp_c,
    }
    return field_map.get(rule_name)


def evaluate_safeguards(
    record: NormalizedHealthRecord,
) -> tuple[RiskLevel, bool, list[RuleExplanation]]:
    """
    Runs every deterministic rule against a normalized record.

    Returns (highest_risk_level, any_rule_triggered, explanations).
    Explanations list ALL rules that were checked (triggered or not) so the
    frontend/LLM can show "why" - not just the final verdict.
    """
    worst = RiskLevel.low
    triggered_any = False
    explanations: list[RuleExplanation] = []

    for name, condition, level, template in _RULES:
        is_triggered = bool(condition(record))
        if is_triggered:
            triggered_any = True
            if _RISK_ORDER[level] > _RISK_ORDER[worst]:
                worst = level
            value = _value_for(record, name)
            detail = template.format(value=value)
        else:
            detail = "not triggered"

        explanations.append(RuleExplanation(rule=name, triggered=is_triggered, detail=detail))

    return worst, triggered_any, explanations
