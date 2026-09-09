import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../lib/api";

type Mode = "login" | "register";

export function LoginForm() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.register(email.trim(), password, fullName);
      } else {
        await api.login(email.trim(), password);
      }
      // success flips App via the hc:auth event
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth card">
      <h1 className="auth__title">Health Companion</h1>

      <div className="auth__tabs" role="tablist">
        {(["login", "register"] as Mode[]).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            className={`auth__tab ${mode === m ? "auth__tab--active" : ""}`}
            onClick={() => {
              setMode(m);
              setError(null);
            }}
          >
            {m === "login" ? "Log in" : "Register"}
          </button>
        ))}
      </div>

      <form className="auth__form" onSubmit={submit}>
        <label>
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        {mode === "register" && (
          <label>
            Full name <span className="auth__optional">(optional)</span>
            <input
              type="text"
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
        )}

        <label>
          Password
          <input
            type="password"
            required
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn btn--block" disabled={busy}>
          {busy ? "Working…" : mode === "login" ? "Log in" : "Create account"}
        </button>
      </form>
    </div>
  );
}
