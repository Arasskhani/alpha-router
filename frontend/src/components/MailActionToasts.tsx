import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useCachedSession } from "../hooks/useCachedSession";
import { MAIL_CHANGED_EVENT, announceMailChanged, mailApi, type ActionItem } from "../lib/exchangeMail";
import { getMyConnectionsPath } from "../lib/rbac";
import { showToast } from "../lib/toastHost";
import { askAlpharouter } from "./mail/askAlpharouter";
import { mailErrorText, senderLabel, subjectLabel } from "./mail/mailFormat";

/** How often the open items are read while the tab is visible. */
export const MAIL_POLL_MS = 2 * 60_000;
/** Focus and "tab visible again" often fire together: one read for both. */
const MIN_GAP_MS = 5_000;
/** At most this many toasts from one read; past it, the last one says how many more. */
export const MAX_MAIL_TOASTS = 3;
const TOAST_TTL_MS = 45_000;

/**
 * Items already shown in this tab. The server is told (POST /notified), but if
 * that call fails the next read would show them again; this keeps them shown
 * once per tab, across a switch between the user and admin panels.
 */
const announced = new Set<number>();

/** Test seam: forget what this tab has shown. */
export function resetMailActionToasts(): void {
  announced.clear();
}

function failureToast(title: string, err: unknown) {
  showToast({ eyebrow: "Email", title, detail: mailErrorText(err, "action"), tone: "danger", ttlMs: 8000 });
}

/**
 * Toasts for emails that need the person's action, mounted once in the shell
 * of both panels. Only while the mailbox is connected and working
 * (`features.exchange_mail`): reads the open items every two minutes while the
 * tab is visible, and on focus; shows a toast for each new one (Ask
 * Alpharouter, Dismiss), at most three, then tells the server they were shown.
 */
export default function MailActionToasts() {
  const session = useCachedSession();
  const features = session?.features as Record<string, unknown> | null | undefined;
  const on = features?.exchange_mail === true;
  const role = typeof session?.role === "string" ? session.role : "user";
  const navigate = useNavigate();
  const location = useLocation();

  // The toasts outlive renders: they read the latest router and role through refs.
  const navigateRef = useRef(navigate);
  const pathRef = useRef(location.pathname);
  const roleRef = useRef(role);
  useEffect(() => {
    navigateRef.current = navigate;
    pathRef.current = location.pathname;
    roleRef.current = role;
  });

  useEffect(() => {
    if (!on) return undefined;
    let live = true;
    let inFlight = false;
    let lastRead = 0;
    /** Toasts on screen from this mount, by item id, with their close functions. */
    const open = new Map<number, () => void>();

    function itemToast(item: ActionItem) {
      const close = showToast({
        eyebrow: "Needs your action",
        title: subjectLabel(item.subject),
        detail: item.reason ? `${senderLabel(item)} · ${item.reason}` : senderLabel(item),
        dedupeKey: `mail-action::${item.id}`,
        ttlMs: TOAST_TTL_MS,
        actions: [
          {
            label: "Ask Alpharouter",
            onClick: () => {
              open.delete(item.id);
              askAlpharouter(item.id, (to) => navigateRef.current(to), pathRef.current).catch((err: unknown) =>
                failureToast("This email could not be opened in a chat.", err),
              );
            },
          },
          {
            label: "Dismiss",
            onClick: () => {
              open.delete(item.id);
              mailApi
                .dismissAction(item.id)
                .then(() => announceMailChanged())
                .catch((err: unknown) => failureToast("This email could not be dismissed.", err));
            },
          },
        ],
      });
      open.set(item.id, close);
    }

    function moreToast(count: number) {
      showToast({
        eyebrow: "Email",
        title: `${count} more emails need your action`,
        detail: "Open Connections to see them.",
        dedupeKey: "mail-action::more",
        ttlMs: TOAST_TTL_MS,
        onClick: () => navigateRef.current(`${getMyConnectionsPath(roleRef.current)}#mail-actions`),
      });
    }

    async function read(force: boolean) {
      if (!live || inFlight || document.hidden) return;
      if (!force && Date.now() - lastRead < MIN_GAP_MS) return;
      inFlight = true;
      lastRead = Date.now();
      try {
        const { items } = await mailApi.actionItems("open");
        if (!live) return;
        // Handled elsewhere (the Connections page, another tab): its toast goes.
        const stillOpen = new Set(items.map((item) => item.id));
        for (const [id, close] of open) {
          if (!stillOpen.has(id)) {
            close();
            open.delete(id);
          }
        }
        const fresh = items.filter((item) => item.status === "new" && !announced.has(item.id));
        if (fresh.length === 0) return;
        const single = fresh.length <= MAX_MAIL_TOASTS ? fresh : fresh.slice(0, MAX_MAIL_TOASTS - 1);
        single.forEach(itemToast);
        if (fresh.length > single.length) moreToast(fresh.length - single.length);
        const ids = fresh.map((item) => item.id);
        ids.forEach((id) => announced.add(id));
        await mailApi.markNotified(ids).catch(() => undefined);
      } catch {
        // Quiet: the next read tries again, and Connections shows any problem.
      } finally {
        inFlight = false;
      }
    }

    const onTick = () => void read(false);
    const onWake = () => void read(false);
    const onVisibility = () => {
      if (!document.hidden) void read(false);
    };
    const onChanged = () => void read(true);

    void read(true);
    const timer = window.setInterval(onTick, MAIL_POLL_MS);
    window.addEventListener("focus", onWake);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener(MAIL_CHANGED_EVENT, onChanged);
    return () => {
      live = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onWake);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener(MAIL_CHANGED_EVENT, onChanged);
      for (const close of open.values()) close();
      open.clear();
    };
  }, [on]);

  return null;
}
