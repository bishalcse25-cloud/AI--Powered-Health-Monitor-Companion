/**
 * Local, browser-only alerting for the Live Monitor: a short attention tone
 * (Web Audio, no asset file) plus an optional desktop notification. Used when
 * the wearable raises a fall alert.
 */

let audioCtx: AudioContext | null = null;

function ctx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  audioCtx ??= new Ctor();
  return audioCtx;
}

/** Two-tone "ping ping" alarm, ~0.7s total. Safe to call repeatedly. */
export function playAlarm(): void {
  const ac = ctx();
  if (!ac) return;
  if (ac.state === "suspended") void ac.resume();

  const now = ac.currentTime;
  for (const [start, freq] of [[0, 880], [0.35, 988]] as const) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, now + start);
    gain.gain.exponentialRampToValueAtTime(0.3, now + start + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + start + 0.3);
    osc.connect(gain).connect(ac.destination);
    osc.start(now + start);
    osc.stop(now + start + 0.32);
  }
}

export type NotifyPermission = "default" | "granted" | "denied" | "unsupported";

export function notificationPermission(): NotifyPermission {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission;
}

export async function requestNotificationPermission(): Promise<NotifyPermission> {
  if (typeof Notification === "undefined") return "unsupported";
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

export function sendNotification(title: string, body: string): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    new Notification(title, { body, tag: "hc-fall-alert", icon: "/icon-192.png" });
  } catch {
    /* some browsers require a ServiceWorkerRegistration for notifications */
  }
}
