/**
 * The one place a transient message is put on screen.
 *
 * This began as private raw-DOM code inside `replyReadyNotify`, which called
 * `host.replaceChildren()` on every message — fine while "reply ready" was the
 * only toast in the product, and wrong the moment a second kind existed: a
 * budget warning would silently erase a reply notification, and vice versa.
 * So the host is shared, it queues rather than replaces, and each toast owns
 * its own lifetime.
 *
 * Raw DOM rather than React on purpose: a toast has to be able to appear from
 * a stream callback or a module-level helper that has no component to hang
 * off, and outlive the route that triggered it.
 */

const DEFAULT_TTL_MS = 4200;
const MAX_VISIBLE = 3;

type ToastTone = "neutral" | "warning" | "danger";

export type ToastSpec = {
  /** Small kicker above the message. */
  eyebrow: string;
  title: string;
  /** Optional second line; used for the figures behind a budget warning. */
  detail?: string;
  tone?: ToastTone;
  ttlMs?: number;
  /**
   * De-duplication key. A repeat while the toast is still on screen is
   * ignored, which is what keeps a burst of parallel model replies — or two
   * budget checks racing on page load — from stacking the same message.
   */
  dedupeKey?: string;
  onClick?: () => void;
};

let host: HTMLDivElement | null = null;
const live = new Map<string, HTMLElement>();

function ensureHost(): HTMLDivElement {
  if (host && document.body.contains(host)) return host;
  const el = document.createElement("div");
  el.className = "app-toast-host";
  el.setAttribute("aria-live", "polite");
  document.body.appendChild(el);
  host = el;
  return el;
}

function dismiss(key: string, node: HTMLElement) {
  if (live.get(key) === node) live.delete(key);
  node.remove();
}

export function showToast(spec: ToastSpec): void {
  if (typeof document === "undefined") return;
  const key = spec.dedupeKey || `${spec.eyebrow}::${spec.title}`;
  if (live.has(key)) return;

  const root = ensureHost();
  const interactive = typeof spec.onClick === "function";
  const node = document.createElement(interactive ? "button" : "div");
  if (node instanceof HTMLButtonElement) node.type = "button";
  node.className = `app-toast app-toast--${spec.tone || "neutral"}`;
  if (!interactive) node.setAttribute("role", "status");

  const eyebrow = document.createElement("span");
  eyebrow.className = "app-toast__eyebrow";
  eyebrow.textContent = spec.eyebrow;
  const title = document.createElement("span");
  title.className = "app-toast__title";
  title.textContent = spec.title;
  node.append(eyebrow, title);
  if (spec.detail) {
    const detail = document.createElement("span");
    detail.className = "app-toast__detail";
    detail.textContent = spec.detail;
    node.append(detail);
  }

  if (interactive) {
    node.addEventListener("click", () => {
      spec.onClick?.();
      dismiss(key, node);
    });
  }

  root.appendChild(node);
  live.set(key, node);

  // Oldest first, so a burst never pushes the newest message off-screen.
  while (root.childElementCount > MAX_VISIBLE && root.firstElementChild) {
    const stale = root.firstElementChild as HTMLElement;
    for (const [k, v] of live) if (v === stale) live.delete(k);
    stale.remove();
  }

  window.setTimeout(() => dismiss(key, node), spec.ttlMs ?? DEFAULT_TTL_MS);
}

/** Test seam: drop every toast and the host itself. */
export function resetToastHost(): void {
  live.clear();
  host?.remove();
  host = null;
}
