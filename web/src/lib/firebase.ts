/**
 * Live IoT sensor stream (Firebase Realtime Database).
 *
 * The ESP32 wearable in the VigilAI hardware project writes a single JSON
 * object to the root of this Realtime Database ~1x/second. We subscribe to it
 * and turn each snapshot into a normalized {@link LiveVitals} record for the
 * Live Monitor page.
 *
 * The historical dashboard (charts, risk, AI chat) is a completely separate
 * data source — the FastAPI backend in this repo. This module only feeds the
 * real-time view.
 *
 * NOTE ON THE CONFIG BELOW: a Firebase *web* API key is not a secret. It only
 * identifies the project to Google; what a client may actually read/write is
 * controlled by the database's security rules. Google ships it in client
 * bundles by design, so it stays inline here (see web/README.md).
 */

import { initializeApp, getApps } from "firebase/app";
import { getDatabase, ref, onValue, off, type DataSnapshot } from "firebase/database";

const firebaseConfig = {
  apiKey: "AIzaSyAnDdhpJcWGfkHE9YAkFYEULRb8uBuCcIc",
  authDomain: "major-project-1d78c.firebaseapp.com",
  databaseURL: "https://major-project-1d78c-default-rtdb.firebaseio.com",
  projectId: "major-project-1d78c",
  storageBucket: "major-project-1d78c.firebasestorage.app",
  messagingSenderId: "999324211490",
  appId: "1:999324211490:web:0b8cae75dc334f30d8ed7b",
  measurementId: "G-6DZY6F54G5",
};

// initializeApp throws if called twice (e.g. Vite HMR re-imports the module).
const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
const database = getDatabase(app);

/** One reading from the wearable, after coercion + renaming to our conventions. */
export interface LiveVitals {
  /** Client clock time we received the snapshot (ms since epoch). */
  receivedAt: number;
  heartRateBpm: number | null;
  spo2Percent: number | null;
  bodyTempC: number | null;
  pressureHpa: number | null;
  lat: number | null;
  lng: number | null;
  compass: { x: number; y: number; z: number };
  /** true when the wearable is reporting a fall (numeric `fallalert`, or the
   *  `Alert` message string mentions falling). */
  fallAlert: boolean;
  /** human-readable device alert message, raw field `Alert` (e.g. "Person Falling!"). */
  alertMessage: string;
  /** device-reported status code, raw field `STATUS`. */
  status: string;
}

/** Shape the device actually writes to Firebase (all fields best-effort). */
interface RawSnapshot {
  BPM?: number;
  SPO2?: number;
  Temp?: number;
  Pressure?: number;
  Lat?: number;
  Long?: number;
  Compass?: { X?: number; Y?: number; Z?: number };
  /** message string, e.g. "Person Falling!" / "Safe". */
  Alert?: string | number;
  /** clean 0/1 fall flag (preferred when present). */
  fallalert?: number;
  STATUS?: string | number;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseSnapshot(raw: RawSnapshot): LiveVitals {
  const alertMessage = raw.Alert == null ? "" : String(raw.Alert);
  const fallAlert =
    typeof raw.fallalert === "number"
      ? raw.fallalert === 1
      : /fall|falling/i.test(alertMessage);

  return {
    receivedAt: Date.now(),
    heartRateBpm: num(raw.BPM),
    spo2Percent: num(raw.SPO2),
    bodyTempC: num(raw.Temp),
    pressureHpa: num(raw.Pressure),
    lat: num(raw.Lat),
    lng: num(raw.Long),
    compass: {
      x: num(raw.Compass?.X) ?? 0,
      y: num(raw.Compass?.Y) ?? 0,
      z: num(raw.Compass?.Z) ?? 0,
    },
    fallAlert,
    alertMessage,
    status: raw.STATUS == null ? "" : String(raw.STATUS),
  };
}

/**
 * Subscribe to the live sensor feed. `onReading` fires once per Firebase
 * snapshot; `onError` fires if the listener is rejected (e.g. database rules).
 * Returns an unsubscribe function — call it on unmount.
 */
export function subscribeVitals(
  onReading: (v: LiveVitals) => void,
  onError?: (err: Error) => void,
): () => void {
  const rootRef = ref(database, "/");
  const handler = (snap: DataSnapshot) => onReading(parseSnapshot((snap.val() ?? {}) as RawSnapshot));
  onValue(rootRef, handler, (err) => onError?.(err as Error));
  return () => off(rootRef, "value", handler);
}
