import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Progressive Web App: register the service worker for offline app-shell
// caching. Only in production builds — in dev it would cache Vite's HMR
// modules and get in the way.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* SW is a progressive enhancement — ignore registration failures */
    });
  });
}
