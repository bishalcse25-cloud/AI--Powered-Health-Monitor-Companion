import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppBar } from "./components/AppBar";
import { SiteFooter } from "./components/SiteFooter";
import { LoginForm } from "./components/LoginForm";
import { Dashboard } from "./pages/Dashboard";
import { isAuthenticated, onAuthChange } from "./lib/api";

// Live Monitor pulls in Firebase — only load it when that route is visited.
const LiveMonitor = lazy(() =>
  import("./pages/LiveMonitor").then((m) => ({ default: m.LiveMonitor })),
);

export function App() {
  const [authed, setAuthed] = useState(isAuthenticated);

  useEffect(() => onAuthChange((token) => setAuthed(token !== null)), []);

  return (
    <BrowserRouter>
      <div className="app">
        <AppBar authed={authed} />
        <main className="app__inner">
          {authed ? (
            <Suspense fallback={<p className="dashboard__sub">Loading…</p>}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/live" element={<LiveMonitor />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          ) : (
            <LoginForm />
          )}
        </main>
        <SiteFooter />
      </div>
    </BrowserRouter>
  );
}
