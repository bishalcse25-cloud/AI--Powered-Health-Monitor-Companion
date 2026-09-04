"""
LLM AI Companion service.

Builds the CompanionContext (health risk + baseline + trend + recent chat)
and turns it into a system prompt, then streams a reply from Claude.

Mock mode: if LLM_ENABLED=false, or no ANTHROPIC_API_KEY is set in .env,
this returns a canned streaming response instead of calling the API. That
keeps /api/v1/companion/chat fully testable before you add a real key.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import get_settings
from app.schemas import ChatHistoryMessage, CompanionContext

settings = get_settings()

_SYSTEM_PROMPT_TEMPLATE = """You are the Health Companion AI - a supportive, careful assistant \
inside a personal health tracking app. You are NOT a doctor and must never \
diagnose conditions or prescribe treatment. When risk is ELEVATED or \
HIGH_ATTENTION, gently encourage the user to consider contacting a \
healthcare professional, without being alarmist.

Current risk assessment: {risk_level} (score {risk_score:.2f})
Why: {explanations}

7-day baseline: {baseline}

Recent trend: {trend_summary}

Keep replies concise (3-6 sentences unless asked for detail). Always add a \
short reminder that you are not a medical professional when discussing \
symptoms or risk."""


def build_system_prompt(context: CompanionContext) -> str:
    """Section 5.2 of the architecture: the LLM Context Builder."""
    if context.current_risk is not None:
        risk_level = context.current_risk.risk_level.value
        risk_score = context.current_risk.risk_score
        triggered = [e.detail for e in context.current_risk.explanations if e.triggered]
        explanations = "; ".join(triggered) if triggered else "no safeguard rules triggered"
    else:
        risk_level, risk_score, explanations = "UNKNOWN", 0.0, "no recent readings"

    baseline = context.baseline or {"note": "not enough history yet"}
    trend_summary = context.recent_trend_summary or "not enough history yet"

    return _SYSTEM_PROMPT_TEMPLATE.format(
        risk_level=risk_level,
        risk_score=risk_score,
        explanations=explanations,
        baseline=baseline,
        trend_summary=trend_summary,
    )


def _history_to_messages(history: list[ChatHistoryMessage], new_message: str) -> list[dict]:
    messages = [{"role": m.role.value, "content": m.content} for m in history]
    messages.append({"role": "user", "content": new_message})
    return messages


async def _mock_stream(new_message: str) -> AsyncIterator[str]:
    reply = (
        "(mock companion reply - set ANTHROPIC_API_KEY in .env and LLM_ENABLED=true "
        f"for real responses) I heard: \"{new_message[:120]}\". "
        "Based on your current data your risk level looks fine; I'm not a doctor, "
        "so please check with one if anything feels off."
    )
    for word in reply.split(" "):
        yield word + " "


async def stream_reply(context: CompanionContext, new_message: str) -> AsyncIterator[str]:
    """Yields text chunks. Used by routers/companion.py to build an SSE stream."""
    if not settings.llm_enabled or not settings.anthropic_api_key:
        async for chunk in _mock_stream(new_message):
            yield chunk
        return

    import anthropic  # imported lazily so the package is optional until this path runs

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system_prompt = build_system_prompt(context)
    messages = _history_to_messages(context.history, new_message)

    async with client.messages.stream(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
