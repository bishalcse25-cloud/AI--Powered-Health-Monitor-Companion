import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppBar } from "./components/AppBar";
import { SiteFooter } from "./components/SiteFooter";
import { LoginForm } from "./components/LoginForm";
import { Dashboard } from "./pages/Dashboard";
import { LiveMonitor } from "./pages/LiveMonitor";
import { isAuthenticated, onAuthChange } from "./lib/api";

export function App() {
  const [authed, setAuthed] = useState(isAuthenticated);

  useEffect(() => onAuthChange((token) => setAuthed(token !== null)), []);

  return (
    <BrowserRouter>
      <div className="app">
        <AppBar authed={authed} />
        <main className="app__inner">
          {authed ? (
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/live" element={<LiveMonitor />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          ) : (
            <LoginForm />
          )}
        </main>
        <SiteFooter />
      </div>
    </BrowserRouter>
  );
}
