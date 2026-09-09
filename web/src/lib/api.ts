/**
 * Thin API client for the Health Companion backend.
 *
 * - Attaches `Authorization: Bearer <token>` to every request automatically.
 * - Persists the token in localStorage, with an in-memory mirror so it keeps
 *   working when storage is unavailable (private windows).
 * - Normalizes FastAPI error bodies ({detail: string | [{msg}]}) into ApiError.
 * - On any 401 it drops the token and emits a `hc:auth` event so the app can
 *   send the user back to the login screen.
 * - `streamSSE` handles POST + auth-header Server-Sent Events (EventSource
 *   can't do either), yielding parsed events for the chat UI.
 */

import type {
  AuthToken,
  CurrentUser,
  HealthEntry,
  RiskPredictionResponse,
  TrendWindow,
  TrendsResponse,
} from "./types";

const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1"
).replace(/\/+$/, "");

const TOKEN_STORAGE_KEY = "hc_token";
const AUTH_EVENT = "hc:auth";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// --- token store ---------------------------------------------------------

let inMemoryToken: string | null = readStoredToken();

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return inMemoryToken;
}

export function isAuthenticated(): boolean {
  return inMemoryToken !== null;
}

export function setToken(token: string | null): void {
  inMemoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* storage blocked — in-memory token still drives this session */
  }
  window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { token } }));
}

/** Subscribe to login/logout. Returns an unsubscribe fn. */
export function onAuthChange(cb: (token: string | null) => void): () => void {
  const handler = (e: Event) => cb((e as CustomEvent<{ token: string | null }>).detail.token);
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}

// --- request plumbing ---------------------------------------------------

function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (inMemoryToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${inMemoryToken}`);
  }
  return headers;
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail)) {
      // pydantic validation errors
      detail = body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
    }
  } catch {
    /* body wasn't JSON */
  }
  return new ApiError(res.status, detail);
}

function handleFailure(err: ApiError): never {
  if (err.status === 401 && inMemoryToken !== null) {
    setToken(null); // token expired / invalid — force re-login
  }
  throw err;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Plain object -> JSON body, or form-encoded when `form` is true. */
  body?: unknown;
  form?: boolean;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, form, headers, ...rest } = options;
  const init: RequestInit = { ...rest, headers: buildHeaders(headers) };

  if (body !== undefined) {
    const h = init.headers as Headers;
    if (form) {
      h.set("Content-Type", "application/x-www-form-urlencoded");
      init.body = new URLSearchParams(body as Record<string, string>).toString();
    } else {
      h.set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
    }
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "Network error — is the API reachable?");
  }

  if (!res.ok) handleFailure(await toApiError(res));
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --- Server-Sent Events (POST + Authorization) -------------------------

export interface SSEMessage {
  event: string;
  data: string;
}

/**
 * POST `body` to `path` and yield parsed SSE events until the stream closes
 * or `signal` aborts. The backend frames events as
 *   event: <name>\n data: <json>\n\n
 * (a bare `data:` line has event === "message").
 */
export async function* streamSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEMessage> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: buildHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) handleFailure(await toApiError(res));
  if (!res.body) throw new ApiError(0, "This browser can't read streaming responses");

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, "\n");

      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (block.trim()) yield parseSSEBlock(block);
      }
    }
    if (buffer.trim()) yield parseSSEBlock(buffer);
  } finally {
    reader.releaseLock();
  }
}

function parseSSEBlock(block: string): SSEMessage {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return { event, data: data.join("\n") };
}

// --- typed endpoints --------------------------------------------------

export const api = {
  async login(email: string, password: string): Promise<void> {
    // OAuth2 password flow -> form-encoded
    const token = await apiFetch<AuthToken>("/auth/login", {
      method: "POST",
      form: true,
      body: { username: email, password },
    });
    setToken(token.access_token);
  },

  async register(email: string, password: string, fullName?: string): Promise<void> {
    await apiFetch("/auth/register", {
      method: "POST",
      body: { email, password, full_name: fullName?.trim() || null },
    });
    await api.login(email, password);
  },

  logout(): void {
    setToken(null);
  },

  me: () => apiFetch<CurrentUser>("/auth/me"),

  /** Raw stored readings, oldest first — the dashboard's time series. */
  getEntries: (days = 7, limit = 500) =>
    apiFetch<HealthEntry[]>(`/health/entries?days=${days}&limit=${limit}`),

  /** Moving averages + baseline deviation per metric. */
  getTrends: (window: TrendWindow = "7d") =>
    apiFetch<TrendsResponse>(`/health/trends?window=${window}`),

  /** Risk for the user's most recent stored entry (empty body = "use latest"). */
  evaluateLatest: () =>
    apiFetch<RiskPredictionResponse>("/health/evaluate", { method: "POST", body: {} }),

  /** Push a manual reading through the ingest pipeline. */
  ingestReading: (reading: Record<string, number>) =>
    apiFetch<{ accepted: number; status: string }>("/telemetry/ingest", {
      method: "POST",
      body: { source: "manual", readings: [reading] },
    }),

  /** SSE chat stream. Consume with `for await (const evt of ...)`. */
  streamChat: (message: string, conversationId: number | null, signal?: AbortSignal) =>
    streamSSE("/companion/chat", { message, conversation_id: conversationId }, signal),
};
