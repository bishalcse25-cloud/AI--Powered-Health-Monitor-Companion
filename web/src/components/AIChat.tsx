/**
 * AIChat — streams a companion reply from POST /api/v1/companion/chat over SSE.
 *
 * The backend emits:
 *   event: context   data: {"conversation_id": N}   (once, first)
 *   data: {"delta": "text "}                          (many)
 *   event: done       data: {}                        (last)
 *
 * We keep the conversation id in a ref so follow-up messages stay in the same
 * thread, append deltas to the in-progress assistant bubble, and expose a Stop
 * button that aborts the fetch mid-stream.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, streamSSE } from "../lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming: boolean;
}

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export function AIChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const conversationId = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  // Keep the log pinned to the newest message.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const patchAssistant = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    setError(null);
    setInput("");
    setBusy(true);

    const assistantId = newId();
    setMessages((list) => [
      ...list,
      { id: newId(), role: "user", content: text, streaming: false },
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const evt of streamSSE(
        "/companion/chat",
        { message: text, conversation_id: conversationId.current },
        controller.signal,
      )) {
        if (evt.event === "done") break;

        if (evt.event === "context") {
          const id = safeParse(evt.data)?.conversation_id;
          if (typeof id === "number") conversationId.current = id;
          continue;
        }

        // default ("message") events carry {"delta": "..."}
        const delta = safeParse(evt.data)?.delta;
        if (typeof delta === "string" && delta.length > 0) {
          patchAssistant(assistantId, (m) => ({ ...m, content: m.content + delta }));
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof ApiError ? err.detail : "The companion is unavailable right now.");
        // drop the empty assistant bubble if nothing streamed
        setMessages((list) =>
          list.filter((m) => m.id !== assistantId || m.content.length > 0),
        );
      }
    } finally {
      patchAssistant(assistantId, (m) => ({ ...m, streaming: false }));
      setBusy(false);
      abortRef.current = null;
    }
  }, [input, busy, patchAssistant]);

  return (
    <section className="card chat">
      <header className="chat__header">
        <h2>AI companion</h2>
        <span className="chat__disclaimer">Informational support · not a medical professional</span>
      </header>

      <div className="chat__log" ref={logRef}>
        {messages.length === 0 ? (
          <p className="chat__empty">
            Ask about your recent trends, your current risk level, or how you&rsquo;re doing.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`chat__row chat__row--${m.role}`}>
              <span className="chat__who">{m.role === "user" ? "You" : "Companion"}</span>
              <div className="chat__bubble">
                {m.content || (m.streaming ? "" : "…")}
                {m.streaming && <span className="chat__caret" aria-hidden="true" />}
              </div>
            </div>
          ))
        )}
      </div>

      {error && (
        <p className="chat__error" role="alert">
          {error}
        </p>
      )}

      <form
        className="chat__form"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          aria-label="Message the companion"
          disabled={busy}
        />
        {busy ? (
          <button type="button" className="btn btn--ghost" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn" disabled={!input.trim()}>
            Send
          </button>
        )}
      </form>
    </section>
  );
}

function safeParse(raw: string): any {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}
