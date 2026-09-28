/**
 * @vitest-environment happy-dom
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isRendered } from "./extract";
import { OVERLAY_ID, PAUSED_LABEL, hideOverlay, showOverlay } from "./overlay";
import { runAgentCall } from "./runtime";
import { resumeTakeover, runPaused, setDispatching, stopWatching, watchTakeover } from "./takeover";
import { highlightState, showVisuals, VISUALS_ID } from "./visuals";

const RUN = "run-takeover-1";

function page(html: string): void {
  document.body.innerHTML = html;
}

/** A trusted event, as the browser makes for a person's input (a test's own is never trusted). */
function trusted(type: string, target: EventTarget = document.body): Event {
  const event = new Event(type, { bubbles: true, composed: true });
  Object.defineProperty(event, "isTrusted", { value: true });
  target.dispatchEvent(event);
  return event;
}

function banner(): { host: HTMLElement; label: HTMLElement; resume: HTMLButtonElement; stop: HTMLButtonElement } {
  const host = document.getElementById(OVERLAY_ID) as HTMLElement & { __label: HTMLElement; __resume: HTMLButtonElement };
  const buttons = host.__label.parentElement!.querySelectorAll("button");
  return { host, label: host.__label, resume: host.__resume, stop: buttons[buttons.length - 1] as HTMLButtonElement };
}

beforeEach(() => {
  stopWatching();
  document.body.innerHTML = "";
});

describe("a take-over", () => {
  it("pauses the page: the banner says so and offers Resume, the border goes grey, and the panel is told", () => {
    page("<button>Go</button>");
    const send = vi.fn();
    showVisuals(document);
    showOverlay(document, RUN, "Working", send);
    watchTakeover(document, RUN, send);
    expect(banner().resume.style.getPropertyValue("display")).toBe("none");

    trusted("pointerdown", document.querySelector("button")!);

    expect(runPaused(RUN)).toBe(true);
    expect(banner().label.textContent).toBe(PAUSED_LABEL);
    expect(banner().resume.style.getPropertyValue("display")).toBe("inline-block");
    expect(highlightState(document)).toBe("paused");
    expect(send).toHaveBeenCalledWith({ type: "agent-takeover", run: RUN });
    // Once: a second press while paused says nothing new.
    trusted("keydown");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it.each(["pointerdown", "keydown", "wheel"])("is a trusted %s", (type) => {
    page("<p>Page</p>");
    const send = vi.fn();
    watchTakeover(document, RUN, send);
    trusted(type);
    expect(runPaused(RUN)).toBe(true);
  });

  it("is not a synthetic event - the agent's own, without full control - nor a mouse merely moving", () => {
    page("<button>Go</button>");
    const send = vi.fn();
    watchTakeover(document, RUN, send);
    document.querySelector("button")!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    document.querySelector("button")!.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "a" }));
    trusted("pointermove");
    trusted("mousemove");
    expect(runPaused(RUN)).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("is not the agent's own trusted input, sent inside a dispatch window", () => {
    page("<button>Go</button>");
    const send = vi.fn();
    watchTakeover(document, RUN, send);
    expect(setDispatching(true)).toEqual({ paused: false });
    trusted("pointerdown", document.querySelector("button")!);
    trusted("keydown");
    expect(runPaused(RUN)).toBe(false);
    expect(setDispatching(false)).toEqual({ paused: false });
    // The window closed: the next press is the person's.
    trusted("pointerdown", document.querySelector("button")!);
    expect(runPaused(RUN)).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("is not a wheel event of the agent's own scroll that reaches the page just after its window closed", () => {
    page("<p>Page</p>");
    const send = vi.fn();
    watchTakeover(document, RUN, send);
    const now = vi.spyOn(Date, "now").mockReturnValue(10_000);
    try {
      setDispatching(true);
      setDispatching(false);
      // The page's passive wheel listener runs after Chrome answered the scroll.
      now.mockReturnValue(10_400);
      trusted("wheel");
      expect(runPaused(RUN)).toBe(false);
      // A press is the person's at once; a wheel after the grace is too.
      now.mockReturnValue(11_200);
      trusted("wheel");
      expect(runPaused(RUN)).toBe(true);
    } finally {
      now.mockRestore();
    }
  });

  it("is not a press on the agent's own banner or layer", () => {
    page("<p>Page</p>");
    const send = vi.fn();
    showVisuals(document);
    showOverlay(document, RUN, "Working", send);
    watchTakeover(document, RUN, send);
    trusted("pointerdown", document.getElementById(OVERLAY_ID)!);
    trusted("pointerdown", document.getElementById(VISUALS_ID)!);
    expect(runPaused(RUN)).toBe(false);
  });

  it("refuses the actions the panel may still have on their way, though the page can still be read", async () => {
    page("<button>Next</button>");
    const send = vi.fn();
    await runAgentCall(document, "show_overlay", { run: RUN, label: "Working" }, isRendered, send);
    trusted("pointerdown");
    const clicked = vi.fn();
    document.querySelector("button")!.addEventListener("click", clicked);
    const read = await runAgentCall(document, "read_page", {}, isRendered, send, RUN);
    expect(read).toMatchObject({ ok: true });
    const ref = (read as unknown as { elements: Array<{ ref: string }> }).elements[0].ref;
    for (const [method, args] of [["click", { ref }], ["type_text", { ref, text: "x" }], ["press_key", { key: "Enter" }], ["submit_form", { ref }]] as const) {
      await expect(runAgentCall(document, method, args, isRendered, send, RUN)).resolves.toMatchObject({ ok: false, error: "paused" });
    }
    expect(clicked).not.toHaveBeenCalled();
    // The panel asking to send its own input is told the page is paused, and the window does not open.
    await expect(runAgentCall(document, "takeover_dispatch", { on: true }, isRendered, send, RUN)).resolves.toEqual({ ok: true, paused: true });
    // Another run is not paused.
    await expect(runAgentCall(document, "click", { ref }, isRendered, send, "run-other")).resolves.toMatchObject({ ok: true });
  });
});

describe("resuming", () => {
  it("from the banner tells the panel, arms the watch again and puts the border back as it was", () => {
    page("<p>Page</p>");
    const send = vi.fn();
    showVisuals(document);
    showOverlay(document, RUN, "Working", send, () => resumeTakeover(document, RUN, true));
    watchTakeover(document, RUN, send);
    trusted("pointerdown");
    expect(highlightState(document)).toBe("paused");
    banner().resume.click();
    expect(runPaused(RUN)).toBe(false);
    expect(send).toHaveBeenLastCalledWith({ type: "agent-resume", run: RUN });
    expect(banner().label.textContent).toBe("Working");
    expect(banner().resume.style.getPropertyValue("display")).toBe("none");
    expect(highlightState(document)).toBe("working");
    // Armed again: the next press pauses once more.
    trusted("keydown");
    expect(runPaused(RUN)).toBe(true);
    expect(send).toHaveBeenCalledTimes(3);
  });

  it("from the panel says nothing back, and does nothing when not paused", async () => {
    page("<p>Page</p>");
    const send = vi.fn();
    await runAgentCall(document, "show_overlay", { run: RUN, label: "Working" }, isRendered, send);
    await expect(runAgentCall(document, "takeover_resume", { run: RUN }, isRendered, send, RUN)).resolves.toEqual({ ok: true });
    trusted("pointerdown");
    send.mockClear();
    await runAgentCall(document, "takeover_resume", { run: RUN }, isRendered, send, RUN);
    expect(runPaused(RUN)).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("keeps a label the panel gave while paused for after", async () => {
    page("<p>Page</p>");
    const send = vi.fn();
    await runAgentCall(document, "show_overlay", { run: RUN, label: "Working" }, isRendered, send);
    trusted("pointerdown");
    // Every action shows the banner again, with the working label: the pause still shows.
    await runAgentCall(document, "show_overlay", { run: RUN, label: "Filling in the form" }, isRendered, send);
    expect(banner().label.textContent).toBe(PAUSED_LABEL);
    resumeTakeover(document, RUN, false);
    expect(banner().label.textContent).toBe("Filling in the form");
  });
});

describe("the watch", () => {
  it("is one per page however often content.js is injected, and goes with the banner", async () => {
    page("<p>Page</p>");
    const send = vi.fn();
    for (let i = 0; i < 3; i += 1) await runAgentCall(document, "show_overlay", { run: RUN, label: "Working" }, isRendered, send);
    trusted("pointerdown");
    expect(send).toHaveBeenCalledTimes(1);
    await runAgentCall(document, "hide_overlay", { run: RUN }, isRendered, send);
    expect(runPaused(RUN)).toBe(false);
    trusted("pointerdown");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("belongs to one run: a new run's banner replaces it, an old run's pause with it", async () => {
    page("<p>Page</p>");
    const send = vi.fn();
    await runAgentCall(document, "show_overlay", { run: RUN, label: "Working" }, isRendered, send);
    trusted("pointerdown");
    await runAgentCall(document, "show_overlay", { run: "run-2", label: "Working" }, isRendered, send);
    expect(runPaused(RUN)).toBe(false);
    expect(runPaused("run-2")).toBe(false);
    hideOverlay(document, "run-2");
  });

  it("is not set up for a run the person stopped from this page", async () => {
    page("<p>Page</p>");
    const send = vi.fn();
    await runAgentCall(document, "show_overlay", { run: "run-stopped-2", label: "Working" }, isRendered, send);
    banner().stop.click();
    await runAgentCall(document, "show_overlay", { run: "run-stopped-2", label: "Working" }, isRendered, send);
    trusted("pointerdown");
    expect(send).not.toHaveBeenCalledWith({ type: "agent-takeover", run: "run-stopped-2" });
  });
});
