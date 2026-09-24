/**
 * Tells a long-open app that a new version is on the server. An installed app
 * has no address bar or reload button and can stay open for days, so after an
 * upgrade it would keep running the old build until a lazily loaded page failed.
 *
 * When the app becomes visible again (at most every 15 minutes) and hourly
 * while it stays visible, "/" is fetched past every cache and its entry script
 * (/assets/index-<hash>.js) compared with the running one. The same check asks
 * the service worker registration to look for a new or retiring worker. It
 * never reloads by itself: a draft in the composer would be lost.
 * Production builds only.
 */
import { useSyncExternalStore } from "react";

const ENTRY = /\/assets\/index-[\w-]+\.js/;
export const VISIBLE_CHECK_GAP_MS = 15 * 60 * 1000;
export const HOURLY_MS = 60 * 60 * 1000;

let available = false;
let started = false;
let lastCheck = 0;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Show the new-version notice (also used when a page's code fails to load after an upgrade). */
export function markUpdateAvailable(): void {
  if (available) return;
  available = true;
  emit();
}

/** Whether the new-version notice is showing. */
export function useUpdateAvailable(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => available,
    () => false,
  );
}

/** The entry script this page runs, from its module script tag. */
export function runningEntry(doc: Document = document): string | null {
  for (const script of doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]')) {
    const match = ENTRY.exec(script.getAttribute("src") ?? "");
    if (match) return match[0];
  }
  return null;
}

/** Compare the server's current entry script with the running one. */
export async function checkForUpdate(now: number = Date.now()): Promise<boolean> {
  lastCheck = now;
  void navigator.serviceWorker
    ?.getRegistration()
    .then((registration) => registration?.update())
    .catch(() => undefined);
  const running = runningEntry();
  if (!running) return false;
  try {
    const response = await fetch("/", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) return false;
    const latest = ENTRY.exec(await response.text())?.[0];
    if (latest && latest !== running) {
      markUpdateAvailable();
      return true;
    }
  } catch {
    // Offline or restarting: the next check will tell.
  }
  return false;
}

/** Start the checks. Call once at start-up. */
export function startUpdateChecks(): void {
  if (started || !import.meta.env.PROD) return;
  started = true;
  lastCheck = Date.now();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - lastCheck >= VISIBLE_CHECK_GAP_MS) {
      void checkForUpdate();
    }
  });
  window.setInterval(() => {
    if (document.visibilityState === "visible") void checkForUpdate();
  }, HOURLY_MS);
}
