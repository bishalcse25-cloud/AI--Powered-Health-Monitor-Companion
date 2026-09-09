import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../lib/api";
import type { CurrentUser } from "../lib/types";
import { HeartPulseIcon, LogOutIcon } from "./icons";

export function AppBar({ authed }: { authed: boolean }) {
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    if (!authed) {
      setUser(null);
      return;
    }
    let alive = true;
    api
      .me()
      .then((u) => alive && setUser(u))
      .catch(() => alive && setUser(null));
    return () => {
      alive = false;
    };
  }, [authed]);

  return (
    <header className="appbar">
      <div className="appbar__inner">
        <div className="appbar__brand">
          <span className="appbar__logo">
            <HeartPulseIcon width={18} height={18} />
          </span>
          Health Companion
        </div>

        {authed && (
          <nav className="appbar__nav">
            <NavLink to="/" end className={({ isActive }) => `appbar__link${isActive ? " appbar__link--active" : ""}`}>
              Dashboard
            </NavLink>
            <NavLink to="/live" className={({ isActive }) => `appbar__link${isActive ? " appbar__link--active" : ""}`}>
              Live monitor
            </NavLink>
          </nav>
        )}

        <div className="appbar__spacer" />
        {authed && (
          <>
            {user && <span className="appbar__user">{user.full_name || user.email}</span>}
            <button className="btn btn--ghost btn--sm" onClick={() => api.logout()} title="Log out">
              <LogOutIcon width={15} height={15} />
              Log out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
