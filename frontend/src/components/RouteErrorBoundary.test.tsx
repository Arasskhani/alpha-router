/**
 * @vitest-environment happy-dom
 *
 * The route error boundary: a page whose code is gone after an upgrade gets a
 * plain "reload" message instead of the raw browser error.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RouteErrorBoundary, { isChunkLoadError } from "./RouteErrorBoundary";

let host: HTMLDivElement;
let root: Root;

function Throws({ message }: { message: string }): never {
  throw new TypeError(message);
}

beforeEach(() => {
  host = document.createElement("div");
  root = createRoot(host);
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  act(() => root.unmount());
  vi.restoreAllMocks();
});

async function render(message: string) {
  await act(async () => {
    root.render(
      <RouteErrorBoundary>
        <Throws message={message} />
      </RouteErrorBoundary>,
    );
  });
}

describe("RouteErrorBoundary", () => {
  it("recognises a failed page load in Chrome, Safari and Firefox wording", () => {
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: https://x/assets/Users-abc.js"))).toBe(
      true,
    );
    expect(isChunkLoadError(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isChunkLoadError(new TypeError("error loading dynamically imported module: https://x/assets/a.js"))).toBe(true);
    expect(isChunkLoadError(new Error("Cannot read properties of undefined"))).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });

  it("says the app was updated and offers only a reload", async () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload }, configurable: true });
    await render("Failed to fetch dynamically imported module: https://x/assets/Users-abc.js");
    expect(host.querySelector("h2")?.textContent).toBe("Alpharouter was updated");
    expect(host.textContent).toContain("Reload to continue.");
    expect(host.textContent).not.toContain("Failed to fetch");
    const buttons = [...host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toEqual(["Reload"]);
    await act(async () => host.querySelector("button")!.click());
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("says the device is offline when a page's code could not be fetched without a connection", async () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    try {
      await render("Failed to fetch dynamically imported module: https://x/assets/Users-abc.js");
      expect(host.querySelector("h2")?.textContent).toBe("You're offline");
      expect(host.textContent).toContain("Reconnect, then reload");
      expect([...host.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Reload"]);
    } finally {
      Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    }
  });

  it("still shows any other error with Try again and Reload", async () => {
    await render("Cannot read properties of undefined");
    expect(host.querySelector("h2")?.textContent).toBe("This page could not be displayed");
    expect(host.textContent).toContain("Cannot read properties of undefined");
    expect([...host.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Try again", "Reload"]);
  });
});
