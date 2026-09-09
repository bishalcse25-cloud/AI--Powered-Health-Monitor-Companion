/**
 * Subscribes to the Firebase live sensor feed and keeps a rolling buffer of
 * the most recent readings for the Live Monitor page.
 *
 *  - `latest`    most recent reading (or null before the first snapshot)
 *  - `history`   up to `maxPoints` readings, oldest first (for the chart)
 *  - `status`    "connecting" | "live" | "error"
 *  - `paused`    when true, new snapshots are ignored (buffer frozen)
 *  - `fallStartedAt`  ms timestamp when a fall alert first went high, else null
 *                     (clears when the device stops reporting the alert)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { subscribeVitals, type LiveVitals } from "../lib/firebase";

export type LiveStatus = "connecting" | "live" | "error";

interface UseLiveVitals {
  latest: LiveVitals | null;
  history: LiveVitals[];
  status: LiveStatus;
  error: string | null;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  fallStartedAt: number | null;
}

export function useLiveVitals(maxPoints = 60): UseLiveVitals {
  const [history, setHistory] = useState<LiveVitals[]>([]);
  const [latest, setLatest] = useState<LiveVitals | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [fallStartedAt, setFallStartedAt] = useState<number | null>(null);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    const unsubscribe = subscribeVitals(
      (reading) => {
        setStatus("live");
        setError(null);
        setFallStartedAt((prev) => {
          if (reading.fallAlert) return prev ?? reading.receivedAt;
          return null;
        });
        if (pausedRef.current) return;
        setLatest(reading);
        setHistory((buf) => {
          const next = buf.length >= maxPoints ? buf.slice(buf.length - maxPoints + 1) : buf.slice();
          next.push(reading);
          return next;
        });
      },
      (err) => {
        setStatus("error");
        setError(err.message || "Lost connection to the sensor feed.");
      },
    );
    return unsubscribe;
  }, [maxPoints]);

  const setPausedStable = useCallback((value: boolean) => setPaused(value), []);

  return { latest, history, status, error, paused, setPaused: setPausedStable, fallStartedAt };
}
