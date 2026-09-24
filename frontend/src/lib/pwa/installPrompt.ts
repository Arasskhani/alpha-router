/**
 * Whether, and how, this device can install Alpharouter as an app. Read with
 * useInstallState(); the listeners start in main.tsx before React renders,
 * because beforeinstallprompt can fire before any component mounts.
 *
 * - running-installed: already open as an installed app. Nothing to offer.
 * - can-prompt: Chrome, Edge or Samsung Internet handed us its install event;
 *   "Install" opens the browser's own dialog.
 * - ios-manual: Safari (or Chrome, Edge, Firefox) on an iPhone or iPad, where
 *   the only way is Share, then Add to Home Screen; we show how.
 * - unavailable: everything else (plain HTTP, Firefox on Android, desktop
 *   Safari, in-app browsers, an app already installed on Android).
 */
import { useSyncExternalStore } from "react";

export type InstallState = "running-installed" | "can-prompt" | "ios-manual" | "unavailable";

/** Chromium's install event; not in the DOM typings. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
let installed = false;
let started = false;
const listeners = new Set<() => void>();
const installedListeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Open as an installed app: a standalone display mode, or iOS's navigator.standalone. */
function runningInstalled(win: Window = window): boolean {
  const modes = ["standalone", "fullscreen", "minimal-ui"];
  if (modes.some((mode) => win.matchMedia?.(`(display-mode: ${mode})`).matches)) return true;
  return (win.navigator as Navigator & { standalone?: boolean }).standalone === true;
}

/**
 * An iPhone or iPad browser that has Add to Home Screen: Safari, or Chrome,
 * Edge or Firefox on iOS (all carry the Safari/ token), over a secure
 * connection. Not the Google app (GSA/, which also says Safari/), Facebook,
 * Instagram or LINE. iPadOS reports "Macintosh", told apart by its touch points.
 */
export function canAddToHomeScreen(userAgent: string, maxTouchPoints: number, secure: boolean): boolean {
  const iosDevice = /iPhone|iPad|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
  if (!iosDevice || !secure) return false;
  if (!/Safari\//.test(userAgent)) return false;
  return !/GSA\/|FBAN|FBAV|Instagram|Line\//.test(userAgent);
}

function computeState(): InstallState {
  if (typeof window === "undefined") return "unavailable";
  if (runningInstalled()) return "running-installed";
  if (installed) return "unavailable";
  if (deferred) return "can-prompt";
  if (canAddToHomeScreen(navigator.userAgent, navigator.maxTouchPoints ?? 0, window.isSecureContext)) {
    return "ios-manual";
  }
  return "unavailable";
}

export function getInstallState(): InstallState {
  return computeState();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The install state, kept current as the browser's events arrive. */
export function useInstallState(): InstallState {
  return useSyncExternalStore(subscribe, computeState, () => "unavailable");
}

/** Called once the app has been installed on this device (Chromium's appinstalled). */
export function onAppInstalled(listener: () => void): () => void {
  installedListeners.add(listener);
  return () => installedListeners.delete(listener);
}

/**
 * Start listening for the browser's install events. Call once, before React
 * renders. The browser's own automatic prompt is held back, so it never appears
 * on a first visit or at sign-in; the app decides when to suggest installing.
 */
export function startInstallListeners(win: Window = window): void {
  if (started) return;
  started = true;
  win.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event as BeforeInstallPromptEvent;
    emit();
  });
  win.addEventListener("appinstalled", () => {
    deferred = null;
    installed = true;
    for (const listener of installedListeners) listener();
    emit();
  });
  // Opening or leaving the installed app's window changes the display mode.
  win.matchMedia?.("(display-mode: standalone)").addEventListener?.("change", emit);
}

/**
 * Open the browser's install dialog. Call it directly in the click handler:
 * browsers require a user gesture, and each event can be used only once.
 * Resolves to the user's answer, or "unavailable" when there is nothing to open.
 */
export function promptInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const event = deferred;
  if (!event) return Promise.resolve("unavailable");
  deferred = null;
  emit();
  void event.prompt().catch(() => undefined);
  return event.userChoice.then(
    (choice) => choice.outcome,
    () => "dismissed" as const,
  );
}
