import { useEffect, useSyncExternalStore } from "react";
import {
  SUPPORT_BASE,
  TICKETS_BASE,
  TICKETS_CHANGED_EVENT,
  ticketsRequest,
  type StaffCounts,
} from "../lib/tickets";
import type { TicketBadgeKey } from "../nav/types";

/**
 * The numbers on the Support and Tickets menu items, shared by every place that
 * draws them (sidebar, phone tab bar, topbar), so there is one request a minute
 * whatever the number of places. A count is only asked for while something
 * shows that menu item: a person without the Tickets menu never asks for it.
 */
export type TicketBadges = {
  /** The person's tickets with a staff reply or status change they have not opened. */
  support: number;
  /** Tickets waiting for staff: new, or the person answered since staff last did. */
  tickets: number;
  /** One of those is Urgent: the Tickets badge turns red. */
  ticketsUrgent: boolean;
};

const POLL_MS = 60_000;
const EMPTY: TicketBadges = { support: 0, tickets: 0, ticketsUrgent: false };

let state: TicketBadges = EMPTY;
const listeners = new Set<() => void>();
const wanted: Record<TicketBadgeKey, number> = { support: 0, tickets: 0 };
let timer: number | null = null;
let inFlight = false;
/** Something changed while a refresh was in flight: ask again once it is done. */
let dirty = false;
/** Bumped by stop(): a refresh started before it must not fill the store again. */
let generation = 0;

function emit(next: TicketBadges) {
  if (
    next.support === state.support &&
    next.tickets === state.tickets &&
    next.ticketsUrgent === state.ticketsUrgent
  ) {
    return;
  }
  state = next;
  for (const listener of listeners) listener();
}

async function readCounts(): Promise<TicketBadges> {
  const next = { ...state };
  if (wanted.support > 0) {
    try {
      next.support = (await ticketsRequest<{ count: number }>(`${SUPPORT_BASE}/unread`)).count ?? 0;
    } catch {
      next.support = 0;
    }
  }
  if (wanted.tickets > 0) {
    try {
      const counts = await ticketsRequest<StaffCounts>(`${TICKETS_BASE}/counts`);
      next.tickets = counts.needs_staff ?? 0;
      next.ticketsUrgent = (counts.needs_staff_urgent ?? 0) > 0;
    } catch {
      next.tickets = 0;
      next.ticketsUrgent = false;
    }
  }
  return next;
}

async function refresh(): Promise<void> {
  if (inFlight) {
    dirty = true;
    return;
  }
  inFlight = true;
  const mine = generation;
  try {
    do {
      dirty = false;
      const next = await readCounts();
      if (mine !== generation) return;
      emit(next);
    } while (dirty);
  } finally {
    if (mine === generation) inFlight = false;
  }
}

function onWake() {
  void refresh();
}

/** The minute's poll: skipped while the tab is hidden, made up when it shows again. */
function onTick() {
  if (!document.hidden) void refresh();
}

function onVisibility() {
  if (!document.hidden) void refresh();
}

function start() {
  if (timer !== null) return;
  timer = window.setInterval(onTick, POLL_MS);
  window.addEventListener("focus", onWake);
  window.addEventListener(TICKETS_CHANGED_EVENT, onWake);
  document.addEventListener("visibilitychange", onVisibility);
}

function stop() {
  if (timer === null) return;
  window.clearInterval(timer);
  timer = null;
  window.removeEventListener("focus", onWake);
  window.removeEventListener(TICKETS_CHANGED_EVENT, onWake);
  document.removeEventListener("visibilitychange", onVisibility);
  generation += 1;
  inFlight = false;
  dirty = false;
  emit(EMPTY);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot() {
  return state;
}

/** The menu counts for the badge keys this caller draws; `[]` asks for nothing. */
export function useTicketBadges(keys: TicketBadgeKey[]): TicketBadges {
  const support = keys.includes("support");
  const tickets = keys.includes("tickets");
  useEffect(() => {
    if (!support && !tickets) return;
    if (support) wanted.support += 1;
    if (tickets) wanted.tickets += 1;
    start();
    void refresh();
    return () => {
      if (support) wanted.support -= 1;
      if (tickets) wanted.tickets -= 1;
      if (wanted.support <= 0 && wanted.tickets <= 0) stop();
    };
  }, [support, tickets]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** "9+" above nine. */
export function badgeText(count: number): string {
  return count > 9 ? "9+" : String(count);
}
