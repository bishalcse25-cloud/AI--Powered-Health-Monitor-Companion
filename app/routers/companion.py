"""
Pillar 3: LLM AI Companion.

POST /api/v1/companion/chat - Server-Sent Events (SSE) stream. Injects the
user's current ML risk assessment, baseline, and recent trend into the
system prompt before calling Claude (see services/llm.py::build_system_prompt).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import AIConversation, AIMessage, HealthEntry, User
from app.schemas import ChatHistoryMessage, ChatRole, CompanionChatRequest, CompanionContext
from app.services import baseline as baseline_service
from app.services.llm import build_system_prompt, stream_reply
from app.services.ml_engine import evaluate as ml_evaluate
from app.services.normalization import normalize_reading
from app.schemas import NormalizedHealthRecord, TelemetrySource

router = APIRouter(prefix="/api/v1/companion", tags=["companion"])

_HISTORY_LIMIT = 10


def _get_or_create_conversation(db: Session, user: User, conversation_id: int | None) -> AIConversation:
    if conversation_id is not None:
        convo = (
            db.query(AIConversation)
            .filter(AIConversation.id == conversation_id, AIConversation.user_id == user.id)
            .first()
        )
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo

    convo = AIConversation(user_id=user.id, title="New conversation")
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def _build_context(db: Session, user: User) -> CompanionContext:
    latest = (
        db.query(HealthEntry)
        .filter(HealthEntry.user_id == user.id)
        .order_by(HealthEntry.recorded_at.desc())
        .first()
    )
    current_risk = None
    baseline = baseline_service.get_baseline(db, user.id)

    if latest is not None:
        normalized = NormalizedHealthRecord(
            user_id=user.id,
            recorded_at=latest.recorded_at,
            source=latest.source,
            heart_rate_bpm=latest.heart_rate_bpm,
            spo2_percent=latest.spo2_percent,
            body_temp_c=latest.body_temp_c,
            sleep_hours=latest.sleep_hours,
        )
        current_risk = ml_evaluate(normalized, baseline)

    trend_summary = None
    if baseline.get("avg_hr"):
        trend_summary = (
            f"7-day avg HR {baseline.get('avg_hr')} bpm, "
            f"avg SpO2 {baseline.get('avg_spo2')}%, "
            f"avg sleep {baseline.get('avg_sleep')}h, "
            f"based on {baseline.get('sample_count')} samples."
        )

    return CompanionContext(user_id=user.id, current_risk=current_risk, baseline=baseline, recent_trend_summary=trend_summary)


@router.post("/chat")
async def chat(
    request: CompanionChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = _get_or_create_conversation(db, user, request.conversation_id)

    history_rows = (
        db.query(AIMessage)
        .filter(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.created_at.desc())
        .limit(_HISTORY_LIMIT)
        .all()
    )
    history = [
        ChatHistoryMessage(role=ChatRole(m.role), content=m.content) for m in reversed(history_rows) if m.role in ("user", "assistant")
    ]

    context = _build_context(db, user)
    context.history = history

    user_message = AIMessage(conversation_id=conversation.id, role="user", content=request.message)
    db.add(user_message)
    db.commit()

    async def event_stream():
        full_reply = []
        yield f"event: context\ndata: {json.dumps({'conversation_id': conversation.id})}\n\n"
        async for chunk in stream_reply(context, request.message):
            full_reply.append(chunk)
            yield f"data: {json.dumps({'delta': chunk})}\n\n"

        # Persist the assistant's full reply once streaming is done.
        db_bg = db  # same request-scoped session; request is still open during StreamingResponse
        db_bg.add(
            AIMessage(
                conversation_id=conversation.id,
                role="assistant",
                content="".join(full_reply),
                context_snapshot=context.model_dump(mode="json"),
            )
        )
        db_bg.commit()
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
