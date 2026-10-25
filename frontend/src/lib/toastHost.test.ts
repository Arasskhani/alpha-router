/**
 * @vitest-environment happy-dom
 *
 * The shared toast host: plain toasts and clickable ones as before, and the
 * action buttons the mail toasts need (Ask Alpharouter, Dismiss), plus the
 * close function every toast now hands back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetToastHost, showToast } from "./toastHost";

const toasts = () => [...document.querySelectorAll<HTMLElement>(".app-toast")];

beforeEach(() => {
  vi.useFakeTimers();
  resetToastHost();
});

afterEach(() => {
  resetToastHost();
  vi.useRealTimers();
});

describe("showToast without actions (unchanged)", () => {
  it("shows a status message that goes away on its own", () => {
    showToast({ eyebrow: "Budget", title: "You have used 72%.", detail: "$27.60 left" });
    const [toast] = toasts();
    expect(toast.tagName).toBe("DIV");
    expect(toast.getAttribute("role")).toBe("status");
    expect(toast.textContent).toContain("You have used 72%.");
    expect(toast.querySelector(".app-toast__actions")).toBeNull();
    vi.advanceTimersByTime(4300);
    expect(toasts()).toHaveLength(0);
  });

  it("makes the whole toast a button when it has onClick", () => {
    const onClick = vi.fn();
    showToast({ eyebrow: "Chat ready", title: "Budget plan", onClick });
    const [toast] = toasts();
    expect(toast.tagName).toBe("BUTTON");
    toast.click();
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(toasts()).toHaveLength(0);
  });

  it("ignores a repeat that is still on screen and keeps at most three", () => {
    showToast({ eyebrow: "A", title: "one", dedupeKey: "k" });
    showToast({ eyebrow: "A", title: "one again", dedupeKey: "k" });
    expect(toasts()).toHaveLength(1);
    showToast({ eyebrow: "A", title: "two" });
    showToast({ eyebrow: "A", title: "three" });
    showToast({ eyebrow: "A", title: "four" });
    expect(toasts().map((t) => t.querySelector(".app-toast__title")?.textContent)).toEqual(["two", "three", "four"]);
  });
});

describe("showToast with actions", () => {
  it("draws one button per action inside a group, not a button in a button", () => {
    showToast({
      eyebrow: "Needs your action",
      title: "Budget approval",
      actions: [
        { label: "Ask Alpharouter", onClick: () => {} },
        { label: "Dismiss", onClick: () => {} },
      ],
    });
    const [toast] = toasts();
    expect(toast.tagName).toBe("DIV");
    expect(toast.getAttribute("role")).toBe("group");
    expect(toast.getAttribute("aria-label")).toBe("Budget approval");
    const buttons = [...toast.querySelectorAll<HTMLButtonElement>(".app-toast__action")];
    expect(buttons.map((b) => b.textContent)).toEqual(["Ask Alpharouter", "Dismiss"]);
    expect(buttons.every((b) => b.type === "button")).toBe(true);
  });

  it("runs the pressed action once and closes the toast", () => {
    const ask = vi.fn();
    const dismiss = vi.fn();
    showToast({
      eyebrow: "Needs your action",
      title: "Budget approval",
      actions: [
        { label: "Ask Alpharouter", onClick: ask },
        { label: "Dismiss", onClick: dismiss },
      ],
    });
    toasts()[0].querySelectorAll<HTMLButtonElement>(".app-toast__action")[1].click();
    expect(dismiss).toHaveBeenCalledTimes(1);
    expect(ask).not.toHaveBeenCalled();
    expect(toasts()).toHaveLength(0);
  });

  it("ignores onClick when there are actions: a click on the text does nothing", () => {
    const onClick = vi.fn();
    showToast({ eyebrow: "E", title: "T", onClick, actions: [{ label: "Go", onClick: () => {} }] });
    toasts()[0].click();
    expect(onClick).not.toHaveBeenCalled();
    expect(toasts()).toHaveLength(1);
  });

  it("drops actions without a label", () => {
    showToast({ eyebrow: "E", title: "T", actions: [{ label: "", onClick: () => {} }] });
    expect(toasts()[0].getAttribute("role")).toBe("status");
    expect(toasts()[0].querySelector(".app-toast__actions")).toBeNull();
  });

  it("keeps its own lifetime", () => {
    showToast({ eyebrow: "E", title: "T", ttlMs: 60_000, actions: [{ label: "Go", onClick: () => {} }] });
    vi.advanceTimersByTime(59_000);
    expect(toasts()).toHaveLength(1);
    vi.advanceTimersByTime(1_500);
    expect(toasts()).toHaveLength(0);
  });
});

describe("the close function", () => {
  it("closes the toast early and is harmless afterwards", () => {
    const close = showToast({ eyebrow: "E", title: "T", dedupeKey: "mail::1" });
    expect(toasts()).toHaveLength(1);
    close();
    expect(toasts()).toHaveLength(0);
    close();
    // The key is free again.
    showToast({ eyebrow: "E", title: "T", dedupeKey: "mail::1" });
    expect(toasts()).toHaveLength(1);
  });

  it("closes the toast already on screen when the call was a repeat", () => {
    showToast({ eyebrow: "E", title: "T", dedupeKey: "mail::2" });
    const close = showToast({ eyebrow: "E", title: "T", dedupeKey: "mail::2" });
    close();
    expect(toasts()).toHaveLength(0);
  });

  it("does not close a newer toast that took the same key", () => {
    const close = showToast({ eyebrow: "E", title: "old", dedupeKey: "mail::3" });
    close();
    showToast({ eyebrow: "E", title: "new", dedupeKey: "mail::3" });
    close();
    expect(toasts().map((t) => t.querySelector(".app-toast__title")?.textContent)).toEqual(["new"]);
  });
});
