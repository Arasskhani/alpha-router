/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHONE_QUERY, useMediaQuery, usePhoneLayout } from "./useMediaQuery";

type Listener = (event: { matches: boolean }) => void;

/** A matchMedia whose answer the test flips. */
function fakeMatchMedia(initial: Record<string, boolean>) {
  const listeners = new Map<string, Set<Listener>>();
  const matches = { ...initial };
  const matchMedia = vi.fn((query: string) => ({
    get matches() {
      return matches[query] ?? false;
    },
    media: query,
    addEventListener: (_: "change", fn: Listener) => {
      if (!listeners.has(query)) listeners.set(query, new Set());
      listeners.get(query)!.add(fn);
    },
    removeEventListener: (_: "change", fn: Listener) => listeners.get(query)?.delete(fn),
  }));
  return {
    matchMedia,
    flip(query: string, value: boolean) {
      matches[query] = value;
      for (const fn of listeners.get(query) ?? []) fn({ matches: value });
    },
    listenerCount: (query: string) => listeners.get(query)?.size ?? 0,
  };
}

let host: HTMLDivElement;
let root: Root;
const originalMatchMedia = window.matchMedia;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.matchMedia = originalMatchMedia;
});

function Probe({ query }: { query: string }) {
  return <output>{useMediaQuery(query) ? "matches" : "no"}</output>;
}

describe("useMediaQuery", () => {
  it("answers from matchMedia and follows its changes", async () => {
    const query = "(max-width: 768px)";
    const fake = fakeMatchMedia({ [query]: true });
    window.matchMedia = fake.matchMedia as unknown as typeof window.matchMedia;
    await act(async () => root.render(<Probe query={query} />));
    expect(host.textContent).toBe("matches");
    await act(async () => fake.flip(query, false));
    expect(host.textContent).toBe("no");
    await act(async () => fake.flip(query, true));
    expect(host.textContent).toBe("matches");
  });

  it("unsubscribes when the component goes", async () => {
    const query = "(max-width: 111px)";
    const fake = fakeMatchMedia({ [query]: false });
    window.matchMedia = fake.matchMedia as unknown as typeof window.matchMedia;
    await act(async () => root.render(<Probe query={query} />));
    expect(fake.listenerCount(query)).toBe(1);
    await act(async () => root.render(<div />));
    expect(fake.listenerCount(query)).toBe(0);
  });

  it("is false where matchMedia does not exist, instead of throwing", async () => {
    (window as { matchMedia?: unknown }).matchMedia = undefined;
    await act(async () => root.render(<Probe query="(max-width: 222px)" />));
    expect(host.textContent).toBe("no");
  });

  it("usePhoneLayout asks the query styles.css uses", async () => {
    const fake = fakeMatchMedia({ [PHONE_QUERY]: true });
    window.matchMedia = fake.matchMedia as unknown as typeof window.matchMedia;
    function Phone() {
      return <output>{usePhoneLayout() ? "phone" : "wide"}</output>;
    }
    await act(async () => root.render(<Phone />));
    expect(PHONE_QUERY).toBe("(max-width: 768px)");
    expect(host.textContent).toBe("phone");
  });
});
