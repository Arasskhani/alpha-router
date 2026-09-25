/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const confirm = vi.fn();
vi.mock("../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm, prompt: vi.fn() }) }));
vi.mock("../lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));

import { api } from "../api";
import { copyTextToClipboard } from "../lib/clipboard";
import ExtensionPanel from "./ExtensionPanel";

const INFO = {
  available: true,
  permitted: true,
  reason: null,
  version: "1.0.0.7",
  extension_id: "abcdefghijklmnopabcdefghijklmnop",
  update_url: "https://ai.example.com/extension/update.xml",
  gpo_value: "abcdefghijklmnopabcdefghijklmnop;https://ai.example.com/extension/update.xml",
};

const LAPTOP = {
  id: "11111111-1111-1111-1111-111111111111",
  device_name: "Chrome on Windows",
  created_at: "2026-09-20T08:00:00",
  last_used_at: "2026-09-25T09:30:00",
  last_ip: "10.0.0.5",
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  confirm.mockReset();
  vi.mocked(copyTextToClipboard).mockClear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function serve(info: Record<string, unknown>, sessions: unknown[] = []) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/extension/info") return info as never;
    if (path === "/api/extension/sessions") return { items: sessions } as never;
    return {} as never;
  });
}

async function render() {
  await act(async () => {
    root.render(<ExtensionPanel />);
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
  if (!found) throw new Error(`no ${label} button`);
  return found as HTMLButtonElement;
}

describe("Settings → Extension", () => {
  it("offers this server's extension for download with the install steps", async () => {
    serve(INFO);
    await render();
    const link = host.querySelector('a[href="/api/extension/download"]');
    expect(link?.hasAttribute("download")).toBe(true);
    expect(host.textContent).toContain("Version 1.0.0.7");
    expect(host.textContent).toContain("chrome://extensions");
    expect(host.textContent).toContain("Load unpacked");
  });

  it("shows Edge's steps when Edge is chosen", async () => {
    serve(INFO);
    await render();
    await act(async () => button("Edge").click());
    expect(host.textContent).toContain("edge://extensions");
    expect(host.textContent).not.toContain("chrome://extensions");
    expect(button("Edge").getAttribute("aria-pressed")).toBe("true");
  });

  it("tells a user the admin left out, without a download", async () => {
    serve({ ...INFO, permitted: false });
    await render();
    expect(host.textContent).toContain("not enabled for your account");
    expect(host.querySelector('a[href="/api/extension/download"]')).toBeNull();
    expect(host.textContent).not.toContain("For IT");
  });

  it("says why the server cannot hand it out", async () => {
    serve({ ...INFO, available: false, reason: "The browser extension is not built on this server." });
    await render();
    expect(host.textContent).toContain("not built on this server");
    expect(host.querySelector('a[href="/api/extension/download"]')).toBeNull();
  });

  it("lists connected browsers and disconnects one after confirming", async () => {
    serve(INFO, [LAPTOP]);
    await render();
    expect(host.textContent).toContain("Chrome on Windows");
    expect(host.textContent).toContain("10.0.0.5");
    confirm.mockResolvedValueOnce(true);
    await act(async () => button("Disconnect").click());
    expect(api).toHaveBeenCalledWith(`/api/extension/sessions/${LAPTOP.id}`, { method: "DELETE" });
    expect(host.querySelector('[role="status"]')?.textContent).toContain("was disconnected");
  });

  it("does nothing when the disconnect is not confirmed", async () => {
    serve(INFO, [LAPTOP]);
    await render();
    confirm.mockResolvedValueOnce(false);
    await act(async () => button("Disconnect").click());
    expect(vi.mocked(api).mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "DELETE")).toBe(false);
  });

  it("says when no browser is connected, and that signing out disconnects them", async () => {
    serve(INFO, []);
    await render();
    expect(host.textContent).toContain("No browser is connected.");
    expect(host.textContent).toContain("Signing out");
  });

  it("gives IT the ID, the update URL and the policy value to copy", async () => {
    serve(INFO);
    await render();
    await act(async () => button("Copy Policy value").click());
    expect(copyTextToClipboard).toHaveBeenCalledWith(INFO.gpo_value);
    await act(async () => button("Copy Extension ID").click());
    expect(copyTextToClipboard).toHaveBeenCalledWith(INFO.extension_id);
    await act(async () => button("Copy Update URL").click());
    expect(copyTextToClipboard).toHaveBeenCalledWith(INFO.update_url);
  });

  it("shows a failure to load as an announced error", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Server unavailable"));
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Server unavailable");
  });

  it("never claims no browser is connected when the list could not be read", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/extension/info") return INFO as never;
      throw new Error("Server unavailable");
    });
    await render();
    expect(host.textContent).not.toContain("No browser is connected.");
    expect(host.textContent).toContain("Could not load your connected browsers");
    // The rest of the tab still works.
    expect(host.querySelector('a[href="/api/extension/download"]')).not.toBeNull();
  });

  it("reloads the list after a failed disconnect too", async () => {
    serve(INFO, [LAPTOP]);
    await render();
    const listCalls = () => vi.mocked(api).mock.calls.filter(([path]) => path === "/api/extension/sessions").length;
    const before = listCalls();
    confirm.mockResolvedValueOnce(true);
    vi.mocked(api).mockImplementationOnce(async () => {
      throw new Error("No such connected browser.");
    });
    await act(async () => button("Disconnect").click());
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("No such connected browser.");
    expect(listCalls()).toBe(before + 1);
  });

  it("names each Disconnect button after its browser", async () => {
    serve(INFO, [LAPTOP, { ...LAPTOP, id: "22222222-2222-2222-2222-222222222222", device_name: "Edge on Mac" }]);
    await render();
    const labels = [...host.querySelectorAll("button")]
      .filter((b) => b.textContent === "Disconnect")
      .map((b) => b.getAttribute("aria-label"));
    expect(labels).toEqual(["Disconnect Chrome on Windows", "Disconnect Edge on Mac"]);
  });
});
