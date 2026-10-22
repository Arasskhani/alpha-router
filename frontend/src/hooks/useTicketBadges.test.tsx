/**
 * @vitest-environment happy-dom
 *
 * The menu-count store behind the Support and Tickets badges: a change
 * announced while a refresh is in flight is not lost, a refresh that outlives
 * the last badge does not fill the store again, and nothing is polled while
 * the tab is hidden (it catches up when the tab shows again).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => vi.fn());
vi.mock("../lib/tickets", async (importOriginal) => {
  const real = await importOriginal<typeof import("../lib/tickets")>();
  return { ...real, ticketsRequest: request };
});

import { TICKETS_CHANGED_EVENT } from "../lib/tickets";
import type { TicketBadgeKey } from "../nav/types";

type Hook = typeof import("./useTicketBadges").useTicketBadges;

let useTicketBadges: Hook;
let host: HTMLDivElement;
let root: Root;
let hidden = false;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function Badge({ keys, id }: { keys: TicketBadgeKey[]; id: string }) {
  const badges = useTicketBadges(keys);
  return <output data-testid={id}>{badges.tickets}</output>;
}

const shown = (id: string) => host.querySelector(`[data-testid="${id}"]`)?.textContent;
const countCalls = () => request.mock.calls.filter(([url]) => String(url).endsWith("/counts")).length;

async function flush() {
  for (let i = 0; i < 4; i += 1) await act(async () => undefined);
}

beforeEach(async () => {
  vi.resetModules();
  request.mockReset();
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  ({ useTicketBadges } = await import("./useTicketBadges"));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe("the badge store", () => {
  it("asks again when a change is announced during a refresh", async () => {
    const first = deferred<unknown>();
    request.mockImplementationOnce(() => first.promise).mockResolvedValue({ needs_staff: 7, needs_staff_urgent: 0 });
    await act(async () => root.render(<Badge keys={["tickets"]} id="t" />));
    expect(countCalls()).toBe(1);

    // A reply was sent while the first answer is still on its way.
    act(() => {
      window.dispatchEvent(new Event(TICKETS_CHANGED_EVENT));
    });
    expect(countCalls()).toBe(1);

    await act(async () => first.resolve({ needs_staff: 3, needs_staff_urgent: 0 }));
    await flush();
    expect(countCalls()).toBe(2);
    expect(shown("t")).toBe("7");
  });

  it("does not fill the store again with a refresh that outlives the last badge", async () => {
    const pending = deferred<unknown>();
    request.mockImplementationOnce(() => pending.promise);
    await act(async () =>
      root.render(
        <>
          <Badge keys={["tickets"]} id="t" />
          <Badge keys={[]} id="watcher" />
        </>,
      ),
    );
    // The Tickets badge goes away (a role change, a sign-out) before the answer comes.
    await act(async () => root.render(<Badge keys={[]} id="watcher" />));
    await act(async () => pending.resolve({ needs_staff: 5, needs_staff_urgent: 1 }));
    await flush();
    expect(shown("watcher")).toBe("0");

    // A badge drawn again afterwards asks afresh rather than waiting on the old request.
    request.mockResolvedValue({ needs_staff: 2, needs_staff_urgent: 0 });
    await act(async () =>
      root.render(
        <>
          <Badge keys={["tickets"]} id="t" />
          <Badge keys={[]} id="watcher" />
        </>,
      ),
    );
    await flush();
    expect(countCalls()).toBe(2);
    expect(shown("watcher")).toBe("2");
  });

  it("skips the minute's poll while the tab is hidden and catches up when it shows", async () => {
    vi.useFakeTimers();
    request.mockResolvedValue({ needs_staff: 1, needs_staff_urgent: 0 });
    await act(async () => root.render(<Badge keys={["tickets"]} id="t" />));
    await flush();
    expect(countCalls()).toBe(1);

    hidden = true;
    await act(async () => {
      vi.advanceTimersByTime(3 * 60_000);
    });
    await flush();
    expect(countCalls()).toBe(1);

    hidden = false;
    request.mockResolvedValue({ needs_staff: 4, needs_staff_urgent: 0 });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await flush();
    expect(countCalls()).toBe(2);
    expect(shown("t")).toBe("4");

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    await flush();
    expect(countCalls()).toBe(3);
  });
});
