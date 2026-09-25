/**
 * @vitest-environment happy-dom
 *
 * Two things this holds, both of which were wrong before.
 *
 * The tab was called "Personalization" and offered nothing to personalize —
 * four read-only directory fields. A tab name has to say what the user can do
 * there or what the thing is; with nothing to do, only the second is honest.
 *
 * And the screen read those fields out of the memories bundle, so it shared a
 * request with an unrelated feature. Memory and Work profile now each call
 * their own endpoint and each fail on their own.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// SettingsModal pulls in chat storage, which claims a Web Locks leader lock at
// import time; happy-dom has no navigator.locks.
vi.hoisted(() => {
  Object.defineProperty(globalThis.navigator, "locks", {
    configurable: true,
    value: { request: async () => undefined },
  });
});

vi.mock("../api", () => ({
  api: vi.fn(),
  authFetch: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: vi.fn(), prompt: vi.fn() }) }));
vi.mock("../lib/replyReadyNotify", () => ({ requestReplyNotifyPermission: vi.fn() }));

import { api } from "../api";
import SettingsModal from "./SettingsModal";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

async function openSettings() {
  await act(async () => {
    root.render(
      <SettingsModal
        open
        onClose={() => {}}
        theme="light"
        onThemeChange={() => {}}
      />,
    );
  });
}

function clickTab(label: string) {
  const tab = [...document.querySelectorAll("button")].find((b) => b.textContent === label);
  return act(async () => tab?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

describe("the Extension tab", () => {
  it("is in the menu and opens the browser extension's panel", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/extension/info") return { available: false, permitted: false } as never;
      if (path === "/api/extension/sessions") return { items: [] } as never;
      return {} as never;
    });
    await openSettings();
    await clickTab("Extension");
    expect(document.body.textContent).toContain("Browser extension");
    expect(api).toHaveBeenCalledWith("/api/extension/info");
  });
});

describe("the settings tabs", () => {
  it("names the directory screen for what it is, not for something it cannot do", async () => {
    vi.mocked(api).mockResolvedValue({});
    await openSettings();
    const labels = [...document.querySelectorAll("button")].map((b) => b.textContent);
    expect(labels).toContain("Work profile");
    expect(labels).not.toContain("Personalization");
  });

  it("loads the work profile from its own endpoint, not from memories", async () => {
    vi.mocked(api).mockResolvedValue({
      company: "BitPin",
      department: "IT",
      job_title: "IT Manager",
      reporting_to: "Yazdan Yazdizadeh",
    });
    await openSettings();
    await clickTab("Work profile");

    const paths = vi.mocked(api).mock.calls.map((call) => String(call[0]));
    expect(paths).toContain("/api/user/work-profile");
    expect(paths.some((path) => path.startsWith("/api/user/memories"))).toBe(false);
    expect(host.textContent).toContain("BitPin");
    expect(host.textContent).toContain("Yazdan Yazdizadeh");
  });

  it("calls the manager field what an employee would call it", async () => {
    vi.mocked(api).mockResolvedValue({ company: null, department: null, job_title: null, reporting_to: "A. Person" });
    await openSettings();
    await clickTab("Work profile");
    expect(host.textContent).toContain("Manager");
    expect(host.textContent).not.toContain("Report to");
  });

  it("says once where the fields come from instead of on every row", async () => {
    vi.mocked(api).mockResolvedValue({ company: "BitPin", department: "IT", job_title: "x", reporting_to: "y" });
    await openSettings();
    await clickTab("Work profile");
    const occurrences = (host.textContent || "").split("user properties").length - 1;
    expect(occurrences).toBe(1);
  });
});
