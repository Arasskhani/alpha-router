/**
 * @vitest-environment happy-dom
 *
 * Admin › Exchange EWS › People: the connected mailboxes page by page, the
 * search (after typing pauses) and the status filter in the request, and
 * Disconnect only after the administrator confirms.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  authFetch: vi.fn(),
  api: vi.fn(async () => []),
  bootstrapSession: vi.fn(async () => ({})),
  formatApiError: (e: unknown) => String(e),
}));
const dialogs = vi.hoisted(() => ({
  confirm: vi.fn(async (_options: { title?: string; message: string }) => true as boolean | "secondary"),
  prompt: vi.fn(async () => null as string | null),
}));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => dialogs }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch } from "../../api";
import { fakeExchangeApi, json, type Call } from "../../components/exchange/testFixtures";
import ExchangeEws from "./ExchangeEws";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];

function useApi(override?: Parameters<typeof fakeExchangeApi>[1]) {
  vi.mocked(authFetch).mockImplementation(fakeExchangeApi(calls, override) as typeof authFetch);
}

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  dialogs.confirm.mockReset();
  dialogs.confirm.mockResolvedValue(true);
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

async function render(path = "/admin/exchange-ews?tab=people") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/exchange-ews" element={<ExchangeEws />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await settle();
}

const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === text);
const rows = () => [...host.querySelectorAll<HTMLTableRowElement>("tbody tr")];
const lastList = () => {
  const call = calls.filter((c) => c.url.startsWith("/api/admin/exchange-ews/connections?")).at(-1)!;
  return Object.fromEntries(new URL(call.url, "http://x").searchParams);
};

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("Exchange EWS people", () => {
  it("lists the first page and moves between pages", async () => {
    await render();
    expect(lastList()).toEqual({ limit: "50", offset: "0" });
    expect(rows()).toHaveLength(50);
    expect(host.textContent).toContain("120 people");
    const first = rows()[0];
    expect(first.textContent).toContain("Sara Karimi");
    expect(first.textContent).toContain("CORP\\s.karimi");
    expect(first.textContent).toContain("s.karimi@corp.example");
    expect(first.textContent).toContain("Connected");
    expect(first.textContent).toContain("2 Full Access");
    expect(first.textContent).toContain("5 min ago");
    expect(host.querySelector(".ews-admin-pager")?.textContent).toContain("1–50 of 120");
    expect(button("‹ Previous")!.disabled).toBe(true);

    await act(async () => button("Next ›")!.click());
    await settle();
    expect(lastList()).toEqual({ limit: "50", offset: "50" });
    expect(host.querySelector(".ews-admin-pager")?.textContent).toContain("51–100 of 120");
    expect(host.textContent).toContain("Page 2 of 3");

    await act(async () => button("Next ›")!.click());
    await settle();
    expect(rows()).toHaveLength(20);
    expect(button("Next ›")!.disabled).toBe(true);

    await act(async () => button("‹ Previous")!.click());
    await settle();
    expect(lastList()).toEqual({ limit: "50", offset: "50" });
  });

  it("searches once typing pauses, from the first page", async () => {
    await render();
    await act(async () => button("Next ›")!.click());
    await settle();
    await type(host.querySelector<HTMLInputElement>('input[aria-label="Search people"]')!, "sara");
    // Not at every key: nothing is asked before the pause.
    expect(lastList().q).toBeUndefined();
    await act(async () => new Promise((resolve) => setTimeout(resolve, 350)));
    await settle();
    expect(lastList()).toEqual({ q: "sara", limit: "50", offset: "0" });
    expect(rows()).toHaveLength(1);
    expect(host.textContent).toContain("1 person");
    expect(host.querySelector(".ews-admin-pager")).toBeNull();
  });

  it("filters by status", async () => {
    await render();
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="Status"]')!;
    await act(async () => {
      select.value = "error";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await settle();
    expect(lastList()).toEqual({ status: "error", limit: "50", offset: "0" });
    expect(rows().every((row) => row.textContent?.includes("Error"))).toBe(true);
    expect(rows()[0].textContent).toContain("Exchange could not be reached");
  });

  it("says when nobody matches", async () => {
    useApi((url) => (url.includes("/connections?") ? { items: [], total: 0 } : undefined));
    await render("/admin/exchange-ews?tab=people&status=error");
    expect(host.textContent).toContain("Nobody matches.");
  });

  it("disconnects only after the administrator confirms", async () => {
    await render();
    dialogs.confirm.mockResolvedValueOnce(false);
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Disconnect Sara Karimi"]')!.click());
    await settle();
    expect(dialogs.confirm).toHaveBeenCalledTimes(1);
    expect(dialogs.confirm.mock.calls[0][0]).toMatchObject({
      title: "Disconnect Sara Karimi's mailbox?",
      confirmLabel: "Disconnect",
      danger: true,
    });
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    const lists = calls.filter((c) => c.url.includes("/connections?")).length;
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Disconnect Sara Karimi"]')!.click());
    await settle();
    const del = calls.find((c) => c.method === "DELETE")!;
    expect(del.url).toBe("/api/admin/exchange-ews/connections/101");
    expect(host.textContent).toContain("Sara Karimi's mailbox was disconnected.");
    // The page is read again.
    expect(calls.filter((c) => c.url.includes("/connections?")).length).toBe(lists + 1);
  });

  it("shows why a disconnect failed", async () => {
    useApi((url, method) =>
      method === "DELETE" ? json(404, { detail: { code: "not_connected", message: "No mailbox is connected." } }) : undefined,
    );
    await render();
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Disconnect Sara Karimi"]')!.click());
    await settle();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("No mailbox is connected.");
  });
});
