/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VIEWPORT_HEIGHT_VAR, useVisualViewportHeight } from "./useVisualViewportHeight";

class FakeViewport extends EventTarget {
  height = 800;
  scale = 1;
}

let host: HTMLDivElement;
let root: Root;
let viewport: FakeViewport;
const original = Object.getOwnPropertyDescriptor(window, "visualViewport");
const originalScrollY = Object.getOwnPropertyDescriptor(window, "scrollY");

function Probe({ active }: { active: boolean }) {
  useVisualViewportHeight(active);
  return null;
}

const value = () => document.documentElement.style.getPropertyValue(VIEWPORT_HEIGHT_VAR);

beforeEach(() => {
  viewport = new FakeViewport();
  Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  if (original) Object.defineProperty(window, "visualViewport", original);
  else delete (window as { visualViewport?: unknown }).visualViewport;
  document.documentElement.style.removeProperty(VIEWPORT_HEIGHT_VAR);
  if (originalScrollY) Object.defineProperty(window, "scrollY", originalScrollY);
  else delete (window as { scrollY?: unknown }).scrollY;
  vi.restoreAllMocks();
});

describe("useVisualViewportHeight", () => {
  it("follows the visual viewport while active, as the keyboard opens and closes", async () => {
    await act(async () => root.render(<Probe active />));
    expect(value()).toBe("800px");
    viewport.height = 452.6;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(value()).toBe("453px");
    viewport.height = 800;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(value()).toBe("800px");
  });

  it("puts a page the keyboard scrolled back at the top", async () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
    await act(async () => root.render(<Probe active />));
    expect(scrollTo).not.toHaveBeenCalled();
    // The keyboard opens and iOS scrolls the focused field into view.
    Object.defineProperty(window, "scrollY", { configurable: true, value: 120 });
    viewport.height = 450;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("leaves the height and the scroll alone while the page is pinch-zoomed", async () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    await act(async () => root.render(<Probe active />));
    Object.defineProperty(window, "scrollY", { configurable: true, value: 300 });
    viewport.scale = 2;
    viewport.height = 400;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(value()).toBe("800px");
    expect(scrollTo).not.toHaveBeenCalled();
    viewport.scale = 1;
    viewport.height = 800;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(value()).toBe("800px");
  });

  it("sets nothing while inactive, and clears the variable when it stops", async () => {
    await act(async () => root.render(<Probe active={false} />));
    expect(value()).toBe("");
    await act(async () => root.render(<Probe active />));
    expect(value()).toBe("800px");
    await act(async () => root.render(<Probe active={false} />));
    expect(value()).toBe("");
    viewport.height = 300;
    await act(async () => viewport.dispatchEvent(new Event("resize")));
    expect(value()).toBe("");
  });

  it("does nothing where there is no visual viewport", async () => {
    delete (window as { visualViewport?: unknown }).visualViewport;
    await act(async () => root.render(<Probe active />));
    expect(value()).toBe("");
  });
});
