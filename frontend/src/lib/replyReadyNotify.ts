/** Lightweight reply-ready notifications when the user is away from that chat/tab. */

export const REPLY_READY_FOCUS_EVENT = "alpha-router:reply-ready-focus";

const DEDUPE_TTL_MS = 2000;
const TOAST_TTL_MS = 4200;
const TITLE_MAX = 72;

type NotifyArgs = {
  sessionId: string;
  activeId: string | null | undefined;
  /** Chat title only — never model output. */
  title: string;
  sound: boolean;
  /** Stable id for this assistant turn (clientMessageId / server id). */
  messageKey: string;
};

const recentKeys = new Map<string, number>();
let audioCtx: AudioContext | null = null;
let toastHost: HTMLDivElement | null = null;
let toastHideTimer: number | null = null;

function pruneDedupe(now: number) {
  for (const [key, at] of recentKeys) {
    if (now - at > DEDUPE_TTL_MS * 4) recentKeys.delete(key);
  }
}

function shouldDedupe(sessionId: string, messageKey: string): boolean {
  const now = Date.now();
  pruneDedupe(now);
  const key = `${sessionId}::${messageKey}`;
  const prev = recentKeys.get(key);
  if (prev != null && now - prev < DEDUPE_TTL_MS) return true;
  // Also coalesce per-session briefly (multi-model bursts).
  const sessionKey = `session::${sessionId}`;
  const sessionPrev = recentKeys.get(sessionKey);
  if (sessionPrev != null && now - sessionPrev < DEDUPE_TTL_MS) return true;
  recentKeys.set(key, now);
  recentKeys.set(sessionKey, now);
  return false;
}

function isUserAwayFromSession(
  sessionId: string,
  activeId: string | null | undefined,
): boolean {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    return true;
  }
  return !activeId || activeId !== sessionId;
}

function truncateTitle(title: string): string {
  const cleaned = (title || "Chat").replace(/\s+/g, " ").trim() || "Chat";
  if (cleaned.length <= TITLE_MAX) return cleaned;
  return `${cleaned.slice(0, TITLE_MAX - 1)}…`;
}

function playLocalBeep() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    if (!audioCtx || audioCtx.state === "closed") {
      audioCtx = new Ctx();
    }
    const ctx = audioCtx;
    if (ctx.state === "suspended") {
      void ctx.resume().catch(() => {});
    }
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.0001;
    osc.connect(gain);
    gain.connect(ctx.destination);
    const t0 = ctx.currentTime;
    gain.gain.exponentialRampToValueAtTime(0.08, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22);
    osc.start(t0);
    osc.stop(t0 + 0.25);
  } catch {
    /* autoplay / AudioContext blocked — fail soft */
  }
}

function ensureToastHost(): HTMLDivElement {
  if (toastHost && document.body.contains(toastHost)) return toastHost;
  const host = document.createElement("div");
  host.className = "reply-ready-toast-host";
  host.setAttribute("aria-live", "polite");
  document.body.appendChild(host);
  toastHost = host;
  return host;
}

function dispatchFocusSession(sessionId: string) {
  window.dispatchEvent(
    new CustomEvent(REPLY_READY_FOCUS_EVENT, { detail: { sessionId } }),
  );
  try {
    window.focus();
  } catch {
    /* ignore */
  }
}

function showInAppToast(sessionId: string, title: string) {
  const host = ensureToastHost();
  host.replaceChildren();
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "reply-ready-toast";
  btn.innerHTML =
    `<span class="reply-ready-toast__eyebrow">Chat ready</span>` +
    `<span class="reply-ready-toast__title"></span>`;
  const titleEl = btn.querySelector(".reply-ready-toast__title");
  if (titleEl) titleEl.textContent = title;
  btn.addEventListener("click", () => {
    dispatchFocusSession(sessionId);
    host.replaceChildren();
  });
  host.appendChild(btn);
  if (toastHideTimer != null) window.clearTimeout(toastHideTimer);
  toastHideTimer = window.setTimeout(() => {
    if (toastHost === host) host.replaceChildren();
    toastHideTimer = null;
  }, TOAST_TTL_MS);
}

function showOsNotification(sessionId: string, title: string) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return false;
  }
  try {
    const n = new Notification("Chat ready", {
      body: title,
      tag: `alpha-router-reply-${sessionId}`,
      silent: true, // we play our own optional beep
    });
    n.onclick = () => {
      dispatchFocusSession(sessionId);
      try {
        n.close();
      } catch {
        /* ignore */
      }
    };
    window.setTimeout(() => {
      try {
        n.close();
      } catch {
        /* ignore */
      }
    }, 8000);
    return true;
  } catch {
    return false;
  }
}

/**
 * Request browser notification permission (call from a user gesture, e.g. Settings toggle).
 * Returns the resulting permission string, or "unsupported".
 */
export async function requestReplyNotifyPermission(): Promise<NotificationPermission | "unsupported"> {
  if (typeof Notification === "undefined") return "unsupported";
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

export function notifyReplyReady(args: NotifyArgs): void {
  const sessionId = (args.sessionId || "").trim();
  const messageKey = (args.messageKey || "").trim() || "unknown";
  if (!sessionId) return;
  if (!isUserAwayFromSession(sessionId, args.activeId)) return;
  if (shouldDedupe(sessionId, messageKey)) return;

  const title = truncateTitle(args.title);
  const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";

  if (hidden) {
    const shown = showOsNotification(sessionId, title);
    if (!shown) {
      // Permission denied / unsupported: nothing visible until tab returns;
      // still try sound (often blocked when hidden — fail soft).
    }
  } else {
    showInAppToast(sessionId, title);
  }

  if (args.sound) playLocalBeep();
}
