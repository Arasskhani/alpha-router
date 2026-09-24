/**
 * @vitest-environment happy-dom
 *
 * useBackOnline: runs when the connection returns, or when the app comes back
 * into view while online, as after iOS paused it in the background.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBackOnline } from "./useBackOnline";

let host: HTMLDivElement;
let root: Root;
const onBack = vi.fn();

function Probe() {
  useBackOnline(onBack);
  return null;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

function setOnline(online: boolean) {
  Object.defineProperty(navigator, "onLine", { value: online, configurable: true });
  window.dispatchEvent(new Event(online ? "online" : "offline"));
}

beforeEach(async () => {
  onBack.mockClear();
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
  host = document.createElement("div");
  root = createRoot(host);
  await act(async () => root.render(<Probe />));
});

afterEach(() => act(() => root.unmount()));

describe("useBackOnline", () => {
  it("runs when the connection comes back", () => {
    setOnline(false);
    expect(onBack).not.toHaveBeenCalled();
    setOnline(true);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("runs when the app comes back into view while online", () => {
    setVisibility("hidden");
    expect(onBack).not.toHaveBeenCalled();
    setVisibility("visible");
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("waits while offline, and while the app is in the background", () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    setVisibility("visible");
    expect(onBack).not.toHaveBeenCalled();
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    setOnline(true);
    expect(onBack).not.toHaveBeenCalled();
  });

  it("stops listening when unmounted", () => {
    act(() => root.unmount());
    setOnline(true);
    expect(onBack).not.toHaveBeenCalled();
    root = createRoot(host);
  });
});
