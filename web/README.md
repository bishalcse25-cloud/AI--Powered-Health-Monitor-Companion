# Health Companion — web

Vite + React + TypeScript frontend. Two pages:

| Route | Page | Data source |
| --- | --- | --- |
| `/` | **Dashboard** — vitals grid, 7/30/90-day trend charts with baseline bands, ML risk badge + reasons, CSV export, AI companion chat | this repo's FastAPI backend (JWT) |
| `/live` | **Live monitor** — real-time vitals cards, streaming chart with warn/danger bands, fall-detection alert (tone + notification), accelerometer, GPS map | Firebase Realtime Database (the ESP32 feed) |

The Live monitor's **Sync to health record** button pushes the current live
reading through `POST /api/v1/telemetry/ingest`, so Firebase data can feed the
backend's ML risk engine, trends and companion.

Installable **PWA**: `public/manifest.webmanifest` + a small app-shell service
worker (`public/sw.js`, registered only in production builds).

## Setup

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://127.0.0.1:8000
```

`npm run build` type-checks (`tsc`) then bundles to `dist/`. `npm run preview`
serves the build.

## Configuration

Copy `.env.example` to `.env.local` to override:

| Var | Default | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api/v1` | where the browser sends API calls (goes through the Vite proxy by default) |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | what the dev proxy forwards `/api` to |

### Firebase

The live sensor feed uses a **public** Firebase Realtime Database. Its web
config is hard-coded in `src/lib/firebase.ts` on purpose — a Firebase web API
key is not a secret (it only identifies the project; access is governed by
database security rules, and Google ships it in client bundles by design). To
point at your own database, replace `firebaseConfig` there.

## Layout

```
src/
  lib/       api.ts (backend client + SSE)  firebase.ts (live feed)
             alerts.ts (tone + notifications)  csv.ts  types.ts
  hooks/     useLiveVitals.ts
  components/ AppBar, LoginForm, AIChat, VitalsGrid, RiskBadge, AlertBanner, icons
  pages/     Dashboard.tsx   LiveMonitor.tsx
public/      manifest.webmanifest, sw.js, icon-*.png
```
