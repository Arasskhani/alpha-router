/**
 * @vitest-environment happy-dom
 *
 * Admin › Exchange EWS: the tabs follow the address, the Overview shows the
 * counts and what is left to set up, and the Access tab edits who may connect
 * through the admin API, with the note that only Active Directory accounts can.
 */
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  authFetch: vi.fn(),
  // The access editor reads the group and role directories itself.
  api: vi.fn(async () => []),
  bootstrapSession: vi.fn(async () => ({})),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: async () => true, prompt: async () => null }),
}));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch } from "../../api";
import { fakeExchangeApi, json, makeSettings, OVERVIEW, type Call } from "../../components/exchange/testFixtures";
import ExchangeEws from "./ExchangeEws";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
const where = { path: "" };

function Probe() {
  const loc = useLocation();
  useEffect(() => {
    where.path = `${loc.pathname}${loc.search}`;
  }, [loc]);
  return null;
}

function useApi(override?: Parameters<typeof fakeExchangeApi>[1], settings?: Parameters<typeof fakeExchangeApi>[2]) {
  vi.mocked(authFetch).mockImplementation(fakeExchangeApi(calls, override, settings) as typeof authFetch);
}

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  vi.mocked(authFetch).mockReset();
  useApi();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function settle() {
  for (let i = 0; i < 4; i += 1) await act(async () => undefined);
}

async function render(path = "/admin/exchange-ews") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Probe />
        <Routes>
          <Route path="/admin/exchange-ews" element={<ExchangeEws />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await settle();
}

const tab = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => b.textContent === name)!;
const stat = (key: string) => host.querySelector<HTMLElement>(`[data-testid="ews-stat-${key}"]`)!;
const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === text);
const link = (text: string) => [...host.querySelectorAll<HTMLAnchorElement>("a")].find((a) => a.textContent?.trim() === text);

describe("the Exchange EWS tabs", () => {
  it("opens on the Overview and keeps the tab in the address", async () => {
    await render();
    expect(tab("Overview").getAttribute("aria-selected")).toBe("true");
    expect(calls.some((c) => c.url === "/api/admin/exchange-ews/overview")).toBe(true);

    await act(async () => tab("Settings").click());
    await settle();
    expect(where.path).toBe("/admin/exchange-ews?tab=settings");
    expect(host.querySelector<HTMLInputElement>("#ews-url")?.value).toBe("https://mail.corp.example/EWS/Exchange.asmx");

    await act(async () => tab("People").click());
    await settle();
    expect(where.path).toBe("/admin/exchange-ews?tab=people");
    expect(calls.some((c) => c.url.startsWith("/api/admin/exchange-ews/connections?"))).toBe(true);

    await act(async () => tab("Overview").click());
    await settle();
    expect(where.path).toBe("/admin/exchange-ews");
  });

  it("opens the tab the address names", async () => {
    await render("/admin/exchange-ews?tab=access");
    expect(tab("Access").getAttribute("aria-selected")).toBe("true");
  });
});

describe("the Overview", () => {
  it("shows the counts and the setup checklist, and links to the guide", async () => {
    await render();
    expect(stat("connected").textContent).toContain("42");
    expect(stat("needs_password").textContent).toContain("3");
    expect(stat("error").textContent).toContain("1");
    expect(stat("eligible").textContent).toContain("180");
    expect(stat("eligible").textContent).toContain("Access list not applied");
    expect(stat("actions").textContent).toContain("57");
    expect(stat("drafts").textContent).toContain("23");
    expect(stat("sent").textContent).toContain("11");
    expect(stat("last_check").textContent).toContain("3 min ago");

    const items = [...host.querySelectorAll(".ews-admin-checklist__item")];
    expect(items.map((li) => li.querySelector(".ews-admin-checklist__title")?.textContent)).toEqual([
      "EWS address saved: done",
      "Connection tested: done",
      "Turned on: done",
      "Who may connect",
    ]);
    expect(items[0].textContent).toContain("https://mail.corp.example/EWS/Exchange.asmx");
    expect(items[1].textContent).toContain("42 people have connected");
    expect(link("Admin Guide › Exchange EWS")?.getAttribute("href")).toBe("/admin/docs#admin-exchange-ews");
    // Nothing warns while Exchange EWS is on.
    expect(host.querySelector(".ews-admin-off")).toBeNull();
  });

  it("says what is left when nothing is set up, with Exchange EWS off", async () => {
    useApi(
      (url) =>
        url === "/api/admin/exchange-ews/overview"
          ? { ...OVERVIEW, counts: { connected: 0, needs_password: 0, error: 0 }, enabled: false, configured: false, last_check_at: null }
          : undefined,
      makeSettings({ enabled: false, ews_url: "" }),
    );
    await render();
    expect(host.querySelector(".ews-admin-off")?.textContent).toContain("Exchange EWS is off.");
    expect(stat("last_check").textContent).toContain("Never");
    const titles = [...host.querySelectorAll(".ews-admin-checklist__title")].map((t) => t.textContent);
    expect(titles.slice(0, 3)).toEqual(["EWS address saved: to do", "Connection tested: to do", "Turned on: to do"]);

    await act(async () => link("Test connection")!.click());
    await settle();
    expect(where.path).toBe("/admin/exchange-ews?tab=settings&focus=test");
    expect(host.querySelector("#ews-admin-test")).not.toBeNull();
  });

  it("opens People filtered by a status from its count", async () => {
    await render();
    await act(async () => stat("needs_password").querySelector("a")!.click());
    await settle();
    expect(where.path).toBe("/admin/exchange-ews?tab=people&status=needs_password");
    const request = calls.filter((c) => c.url.startsWith("/api/admin/exchange-ews/connections?")).at(-1)!;
    expect(new URL(request.url, "http://x").searchParams.get("status")).toBe("needs_password");
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="Status"]')?.value).toBe("needs_password");
  });

  it("offers Try again when the overview cannot be read", async () => {
    let fail = true;
    useApi((url) =>
      url === "/api/admin/exchange-ews/overview" && fail
        ? json(500, { detail: { code: "boom", message: "The database is busy." } })
        : undefined,
    );
    await render();
    expect(host.textContent).toContain("The overview could not be read: The database is busy.");
    fail = false;
    await act(async () => button("Try again")!.click());
    await settle();
    expect(stat("connected").textContent).toContain("42");
  });
});

describe("the Access tab", () => {
  it("edits who may connect through the admin API, with the Active Directory note", async () => {
    await render("/admin/exchange-ews?tab=access");
    expect(host.textContent).toContain("Only accounts that sign in with Active Directory can connect, whatever this list says.");
    expect(calls.some((c) => c.url === "/api/admin/exchange-ews/access" && c.method === "GET")).toBe(true);
    expect(host.textContent).toContain("ACL v2");

    const visibility = host.querySelector<HTMLSelectElement>(".resource-access-editor__visibility select")!;
    expect(visibility.value).toBe("public");
    await act(async () => {
      visibility.value = "private";
      visibility.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => button("Save access")!.click());
    await settle();
    const put = calls.find((c) => c.url === "/api/admin/exchange-ews/access" && c.method === "PUT")!;
    expect(put.body).toEqual({ access_type: "private", grants: [] });
    expect(host.textContent).toContain("Who may connect was saved.");
    expect(host.textContent).toContain("ACL v3");
  });

  it("shows the server's refusal without the error prefix", async () => {
    useApi((url, method) =>
      url === "/api/admin/exchange-ews/access" && method === "PUT"
        ? json(403, { detail: { code: "forbidden", message: "Read-only role: changes not allowed" } })
        : undefined,
    );
    await render("/admin/exchange-ews?tab=access");
    await act(async () => button("Save access")!.click());
    await settle();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("Read-only role: changes not allowed");
  });
});

describe("read-only administrators", () => {
  it("see every tab with nothing to change", async () => {
    readOnly.value = true;
    await render("/admin/exchange-ews?tab=settings");
    expect(host.textContent).toContain("Your role can read these settings but not change them.");
    expect(button("Save settings")).toBeUndefined();
    expect(button("Run test")).toBeUndefined();
    expect(host.querySelector<HTMLInputElement>("#ews-url")?.disabled).toBe(true);
    expect(host.querySelector<HTMLInputElement>("#ews-test-password")?.disabled).toBe(true);
    expect(host.querySelector<HTMLButtonElement>('[role="switch"]')?.disabled).toBe(true);
    expect(
      [...host.querySelectorAll<HTMLInputElement>(".ews-admin-settings input")].every((input) => input.disabled),
    ).toBe(true);

    await act(async () => tab("Access").click());
    await settle();
    expect(button("Save access")?.disabled).toBe(true);

    await act(async () => tab("People").click());
    await settle();
    expect(host.querySelectorAll("tbody tr").length).toBeGreaterThan(0);
    expect(button("Disconnect")).toBeUndefined();
    // Browsing stays open: the search and the filter are not writes.
    expect(host.querySelector<HTMLInputElement>('input[aria-label="Search people"]')?.disabled).toBe(false);
  });
});
