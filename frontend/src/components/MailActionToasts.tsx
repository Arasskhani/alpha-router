import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useCachedSession } from "../hooks/useCachedSession";
import { PHONE_QUERY } from "../hooks/useMediaQuery";
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
const MAX_MAIL_TOASTS = 3;
const TOAST_TTL_MS = 45_000;
/** On a phone one toast stands for them all, for less time: it covers much of a small screen. */
export const PHONE_TOAST_TTL_MS = 20_000;

/**
 * Items already shown in this tab. The server is told (POST /notified), but if
 * that call fails the next read would show them again; this keeps them shown
 * once per tab, across a switch between the user and admin panels.
 */
const announced = new Set<number>();

type KeptItem = { item: ActionItem; until: number; close: () => void };
type KeptCount = { ids: number[]; more: boolean; until: number; close: () => void };

/**
 * The mail toasts on screen, with the time each has left. Each panel's shell
 * mounts its own copy of this component, so a switch between the user and
 * admin panels unmounts one copy (its toasts go with it) and mounts the other,
 * which puts them back for the time they had left: a toast is not lost by
 * moving around the app. Only for the same person, and only while the mailbox
 * works (a copy that finds it off forgets them).
 */
const kept: { owner: string; items: Map<number, KeptItem>; count: KeptCount | null } = {
  owner: "",
  items: new Map(),
  count: null,
};

function forgetKept(owner = ""): void {
  kept.owner = owner;
  kept.items.clear();
  kept.count = null;
}

/** Test seam: forget what this tab has shown. */
export function resetMailActionToasts(): void {
  announced.clear();
  forgetKept();
}

function failureToast(title: string, err: unknown) {
  showToast({ eyebrow: "Email", title, detail: mailErrorText(err, "action"), tone: "danger", ttlMs: 8000 });
}

/** The app's phone layout (≤ 768 px), asked when the toasts are made: they outlive renders. */
function onPhone(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(PHONE_QUERY).matches;
}

/** "3 emails need your action", or "3 more emails need your action" under the ones shown. */
function countTitle(count: number, more: boolean): string {
  return `${count} ${more ? "more " : ""}${count === 1 ? "email needs" : "emails need"} your action`;
}

/**
 * Toasts for emails that need the person's action, mounted once in the shell
 * of both panels. Only while the mailbox is connected and working
 * (`features.exchange_mail`): reads the open items every two minutes while the
 * tab is visible, and on focus; shows a toast for each new one (Ask
 * Alpharouter, Dismiss), at most three, then tells the server they were shown.
 * On a phone one toast says how many need action instead (Open Connections),
 * for a shorter time. Every mail toast has a plain × that only closes it here.
 * A toast still on screen when the person moves to the other panel shows
 * again there (`kept`).
 */
export default function MailActionToasts() {
  const session = useCachedSession();
  const features = session?.features as Record<string, unknown> | null | undefined;
  const on = features?.exchange_mail === true;
  const role = typeof session?.role === "string" ? session.role : "user";
  const owner = typeof session?.username === "string" ? session.username : "";
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
    if (!on) {
      // The mailbox stopped working (or the person changed): its toasts do not come back.
      forgetKept();
      return undefined;
    }
    if (kept.owner !== owner) forgetKept(owner);
    let live = true;
    let inFlight = false;
    let lastRead = 0;

    function itemToast(item: ActionItem, ttlMs = TOAST_TTL_MS) {
      const forget = () => kept.items.delete(item.id);
      const close = showToast({
        eyebrow: "Needs your action",
        title: subjectLabel(item.subject),
        detail: item.reason ? `${senderLabel(item)} · ${item.reason}` : senderLabel(item),
        dedupeKey: `mail-action::${item.id}`,
        ttlMs,
        closable: true,
        onClose: forget,
        actions: [
          {
            label: "Ask Alpharouter",
            onClick: () => {
              forget();
              askAlpharouter(item.id, (to) => navigateRef.current(to), pathRef.current).catch((err: unknown) =>
                failureToast("This email could not be opened in a chat.", err),
              );
            },
          },
          {
            label: "Dismiss",
            onClick: () => {
              forget();
              mailApi
                .dismissAction(item.id)
                .then(() => announceMailChanged())
                .catch((err: unknown) => failureToast("This email could not be dismissed.", err));
            },
          },
        ],
      });
      kept.items.set(item.id, { item, until: Date.now() + ttlMs, close });
    }

    /** The counting toast still on screen, if any (it may have gone by itself). */
    function liveCount() {
      if (kept.count && Date.now() >= kept.count.until) kept.count = null;
      return kept.count;
    }

    /** Put up (or redo, with a new number) the toast that counts `ids`. */
    function countToast(ids: number[], more: boolean, ttlMs: number) {
      kept.count?.close();
      kept.count = null;
      if (ids.length === 0 || ttlMs <= 0) return;
      const close = showToast({
        eyebrow: "Email",
        title: countTitle(ids.length, more),
        detail: ids.length === 1 ? "Open Connections to see it." : "Open Connections to see them.",
        dedupeKey: "mail-action::count",
        ttlMs,
        closable: true,
        onClose: () => {
          kept.count = null;
        },
        actions: [
          {
            label: "Open Connections",
            onClick: () => {
              kept.count = null;
              navigateRef.current(`${getMyConnectionsPath(roleRef.current)}#mail-actions`);
            },
          },
        ],
      });
      kept.count = { ids, more, until: Date.now() + ttlMs, close };
    }

    /** New emails as toasts: one each (at most three) on a wide screen, one for all on a phone. */
    function announce(fresh: ActionItem[]) {
      const shown = liveCount();
      if (onPhone()) {
        const ids = [...(shown?.ids ?? []), ...fresh.map((item) => item.id)];
        countToast(ids, false, PHONE_TOAST_TTL_MS);
        return;
      }
      const single = fresh.length <= MAX_MAIL_TOASTS ? fresh : fresh.slice(0, MAX_MAIL_TOASTS - 1);
      single.forEach((item) => itemToast(item));
      const rest = fresh.slice(single.length).map((item) => item.id);
      if (rest.length) countToast([...(shown?.ids ?? []), ...rest], true, TOAST_TTL_MS);
    }

    /** The toasts the other panel's copy had on screen, for the time they had left. */
    function showKept() {
      const now = Date.now();
      for (const { item, until } of [...kept.items.values()]) {
        kept.items.delete(item.id);
        if (until - now > 1000) itemToast(item, until - now);
      }
      const count = liveCount();
      if (count) countToast(count.ids, count.more, count.until - now);
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
        for (const [id, toast] of [...kept.items]) {
          if (!stillOpen.has(id)) {
            toast.close();
            kept.items.delete(id);
          }
        }
        const counted = liveCount();
        if (counted) {
          const ids = counted.ids.filter((id) => stillOpen.has(id));
          if (ids.length !== counted.ids.length) countToast(ids, counted.more, counted.until - Date.now());
        }
        const fresh = items.filter((item) => item.status === "new" && !announced.has(item.id));
        if (fresh.length === 0) return;
        announce(fresh);
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

    showKept();
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
      // Off the screen with this copy, but kept: the next copy (the other panel's shell) shows them again.
      for (const toast of kept.items.values()) toast.close();
      kept.count?.close();
    };
  }, [on, owner]);

  return null;
}
