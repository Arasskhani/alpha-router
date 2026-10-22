/**
 * @vitest-environment happy-dom
 *
 * Admin › Tickets › the queue: quick views and filters go into the request,
 * "Assign to me" on a row, the assignee picker, bulk actions, a reply or an
 * internal note, pages, and what read-only and Support accounts are offered.
 */
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ authFetch: vi.fn(), api: vi.fn(), formatApiError: (e: unknown) => String(e) }));
const dialogs = vi.hoisted(() => ({
  confirm: vi.fn(async () => true as boolean | "secondary"),
  prompt: vi.fn(async () => null as string | null),
}));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => dialogs }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch } from "../../api";
import { fakeTicketsApi, LIST, makeMeta, type Call } from "../../components/tickets/testFixtures";
import Tickets from "./Tickets";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
const where = { path: "" };
let go: NavigateFunction;

function Probe() {
  const loc = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    go = navigate;
    where.path = `${loc.pathname}${loc.search}`;
  }, [loc, navigate]);
  return null;
}

function useApi(override?: Parameters<typeof fakeTicketsApi>[1]) {
  vi.mocked(authFetch).mockImplementation(fakeTicketsApi(calls, override) as typeof authFetch);
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
  await act(async () => undefined);
  await act(async () => undefined);
  await act(async () => undefined);
}

async function render(path = "/admin/tickets/list", before: string[] = []) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[...before, path]} initialIndex={before.length}>
        <Probe />
        <Routes>
          <Route path="/admin/tickets/list" element={<Tickets />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await settle();
}

const button = (text: string | RegExp, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof text === "string" ? b.textContent?.trim() === text : text.test(b.textContent ?? ""),
  )!;
const lastList = () => calls.filter((c) => /\/api\/admin\/tickets\?/.test(c.url)).at(-1)!.url;
const row = (n: number) => [...host.querySelectorAll<HTMLTableRowElement>("tbody tr")].find((r) => r.textContent?.includes(String(n)))!;
const panel = () => host.querySelector<HTMLElement>(".tickets-detail")!;

async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("the queue", () => {
  it("shows the quick views with their counts and sends the view", async () => {
    await render();
    expect(lastList()).toContain("page=1");
    expect(lastList()).toContain("page_size=50");
    const views = host.querySelector('[aria-label="Quick views"]')!;
    expect([...views.querySelectorAll("button")].map((b) => b.textContent)).toEqual([
      "Needs staff · 5",
      "Mine · 9",
      "Unassigned · 5",
      "All active · 24",
      "Closed",
    ]);
    expect(button("All active · 24").getAttribute("aria-pressed")).toBe("true");
    await act(async () => button("Needs staff · 5").click());
    await settle();
    expect(where.path).toContain("view=needs_staff");
    expect(lastList()).toContain("view=needs_staff");
  });

  it("puts the filters and the search into the request", async () => {
    await render("/admin/tickets/list?page=2");
    await choose(host.querySelector<HTMLSelectElement>('select[aria-label="Priority"]')!, "high");
    expect(lastList()).toContain("priority=high");
    expect(lastList()).toContain("page=1");
    await choose(host.querySelector<HTMLSelectElement>('select[aria-label="Department"]')!, "IT");
    expect(lastList()).toContain("department=IT");
    await type(host.querySelector<HTMLInputElement>('input[aria-label="Search tickets"]')!, "#1047");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 350));
    });
    await settle();
    expect(where.path).toContain("q=%231047");
    expect(lastList()).toContain("q=%231047");
  });

  it("keeps the Overview's assignee filter visible and removable", async () => {
    await render("/admin/tickets/list?view=active&assignee=none");
    expect(lastList()).toContain("assignee=none");
    expect(host.textContent).toContain("Assignee: Unassigned");
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Clear the assignee filter"]')!.click());
    await settle();
    expect(lastList()).not.toContain("assignee=");
  });

  it("marks tickets that need staff and offers Assign to me on unassigned rows", async () => {
    await render();
    expect(row(1047).querySelector(".tickets-unread-dot")).not.toBeNull();
    expect(row(1042).querySelector(".tickets-unread-dot")).toBeNull();
    expect(button("Assign to me", row(1042))).toBeUndefined();
    expect(row(1042).textContent).toContain("→ Majid A.");
    await act(async () => button("Assign to me", row(1047)).click());
    await settle();
    expect(calls.some((c) => c.url.endsWith("/47/assign-to-me") && c.method === "POST")).toBe(true);
    expect(host.textContent).toContain("#1047 is yours now.");
    expect(where.path).not.toContain("ticket=");
  });

  it("assigns from the picker: yourself without an email, someone else with one", async () => {
    await render("/admin/tickets/list?ticket=47");
    expect(panel().textContent).toContain("Reza Ahmadi");
    expect(panel().textContent).toContain("App 2.9.0 · Edge 141");
    expect(panel().textContent).toContain("Ali Mohammadi assigned this to Majid Arasskhani · email sent");
    await act(async () => panel().querySelector<HTMLButtonElement>(".tickets-assignee__btn")!.click());
    const pop = panel().querySelector<HTMLElement>(".tickets-assign-pop")!;
    const me = pop.querySelector<HTMLElement>(".tickets-assign-opt--me")!;
    expect(me.textContent).toContain("Assign to me");
    expect(me.textContent).toContain("Majid Arasskhani · 9 open");
    expect(me.textContent).toContain("no email");
    const ali = button(/Ali Mohammadi/, pop);
    expect(ali.textContent).toContain("Support · 7 open");
    expect(ali.textContent).toContain("gets an email");
    expect(button(/Unassign/, pop)).toBeUndefined();
    await act(async () => ali.click());
    await settle();
    const assign = calls.find((c) => c.url.endsWith("/47/assign"))!;
    expect(assign.body).toEqual({ assignee_id: 2 });

    await act(async () => button("Assign to me", panel()).click());
    await settle();
    expect(calls.some((c) => c.url.endsWith("/47/assign-to-me"))).toBe(true);
  });

  it("changes status, priority and category with PATCH", async () => {
    await render("/admin/tickets/list?ticket=47");
    const [status, priority] = [...panel().querySelectorAll<HTMLSelectElement>(".tickets-panel__controls select")];
    await choose(status, "waiting");
    await choose(priority, "high");
    const patches = calls.filter((c) => c.url.endsWith("/tickets/47") && c.method === "PATCH").map((c) => c.body);
    expect(patches).toEqual([{ status: "waiting" }, { priority: "high" }]);
  });

  it("acts on the selection: assign to someone else once, and close after asking", async () => {
    await render();
    await act(async () => row(1047).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await act(async () => row(1042).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    const bar = host.querySelector<HTMLElement>(".tickets-bulkbar")!;
    expect(bar.textContent).toContain("2 selected");
    expect(bar.textContent).toContain("Assigning someone else sends them one email for all selected tickets");
    await act(async () => button("Assign… ▾", bar).click());
    await act(async () => button(/Leila Farahani/, bar).click());
    await settle();
    expect(calls.find((c) => c.url.endsWith("/bulk"))!.body).toEqual({ ids: [47, 42], action: "assign", assignee_id: 3 });
    expect(host.textContent).toContain("2 tickets assigned to Leila Farahani. They get one email listing them.");

    await act(async () => host.querySelector<HTMLInputElement>('input[aria-label="Select every ticket on this page"]')!.click());
    await act(async () => button("Close", host.querySelector(".tickets-bulkbar")!).click());
    await settle();
    expect(dialogs.confirm).toHaveBeenCalled();
    expect(calls.filter((c) => c.url.endsWith("/bulk")).at(-1)!.body).toEqual({ ids: [47, 42], action: "close" });
  });

  it("sends a reply with a status, or an internal note without one", async () => {
    await render("/admin/tickets/list?ticket=47");
    const text = panel().querySelector<HTMLTextAreaElement>(".tickets-composer textarea")!;
    expect(text.placeholder).toBe("Reply to Reza…");
    await type(text, "We are on it.");
    await choose(panel().querySelector<HTMLSelectElement>('select[aria-label="Status after the reply"]')!, "waiting");
    await act(async () => button("Send reply", panel()).click());
    await settle();
    const reply = calls.find((c) => c.url.endsWith("/47/messages"))!.body as FormData;
    expect(reply.get("body")).toBe("We are on it.");
    expect(reply.get("internal")).toBe("false");
    expect(reply.get("status")).toBe("waiting");

    await act(async () => button("Internal note", panel()).click());
    expect(panel().querySelector(".tickets-composer--note")).not.toBeNull();
    expect(panel().querySelector('select[aria-label="Status after the reply"]')).toBeNull();
    const note = panel().querySelector<HTMLTextAreaElement>(".tickets-composer textarea")!;
    expect(note.placeholder).toBe("Internal note — only administrators see it");
    await type(note, "LDAP bind user expired.");
    await act(async () => button("Add note", panel()).click());
    await settle();
    const sent = calls.filter((c) => c.url.endsWith("/47/messages")).at(-1)!.body as FormData;
    expect(sent.get("internal")).toBe("true");
    expect(sent.get("status")).toBeNull();
  });

  it("refuses an image type the settings do not allow before sending", async () => {
    await render("/admin/tickets/list?ticket=47");
    const input = panel().querySelector<HTMLInputElement>('input[type="file"]')!;
    const svg = new File(["<svg/>"], "logo.svg", { type: "image/svg+xml" });
    Object.defineProperty(input, "files", { value: [svg], configurable: true });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    await settle();
    expect(panel().textContent).toContain("logo.svg: not an allowed image type");
    expect(panel().querySelector(".tickets-thumb")).toBeNull();
  });

  it("pages through a long list", async () => {
    useApi((url) =>
      /\/api\/admin\/tickets\?/.test(url) ? { ...LIST, total: 120, page: url.includes("page=2") ? 2 : 1 } : undefined,
    );
    await render();
    expect(host.querySelector(".tickets-pager")!.textContent).toContain("1–50 of 120");
    await act(async () => button("Next ›").click());
    await settle();
    expect(lastList()).toContain("page=2");
  });

  it("deletes the selection only for a Super Admin, through the delete dialog", async () => {
    await render();
    await act(async () => row(1047).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await act(async () => button("Delete…", host.querySelector(".tickets-bulkbar")!).click());
    await settle();
    expect(calls.find((c) => c.url.endsWith("/delete-preview"))!.body).toEqual({ ids: [47] });
    expect(document.querySelector(".tickets-modal")!.textContent).toContain("Delete the selected ticket");
    expect(document.querySelector(".tickets-filter-summary")!.textContent).toBe("Selected#1047");
  });
});

describe("the queue keeps up", () => {
  it("leaves a page that a bulk close emptied for the last one that has tickets", async () => {
    useApi((url) => {
      if (!/\/api\/admin\/tickets\?/.test(url)) return undefined;
      return url.includes("page=3")
        ? { items: [], total: 60, page: 3, page_size: 50 }
        : { ...LIST, total: 60, page: url.includes("page=2") ? 2 : 1 };
    });
    await render("/admin/tickets/list?page=3");
    await settle();
    expect(where.path).toContain("page=2");
    expect(lastList()).toContain("page=2");
    expect(host.textContent).not.toContain("No ticket matches.");
  });

  it("gives opening a ticket its own history entry; filters replace theirs", async () => {
    await render("/admin/tickets/list", ["/admin/dashboard"]);
    await choose(host.querySelector<HTMLSelectElement>('select[aria-label="Priority"]')!, "high");
    await act(async () => row(1047).querySelector<HTMLButtonElement>(".tickets-row-title")!.click());
    await settle();
    expect(where.path).toContain("ticket=47");
    // Another ticket from the open one: Back still goes to the list.
    await act(async () => row(1042).querySelector<HTMLButtonElement>(".tickets-row-title")!.click());
    await settle();
    expect(where.path).toContain("ticket=42");
    await act(async () => go(-1));
    await settle();
    expect(where.path).toBe("/admin/tickets/list?priority=high");
    await act(async () => go(-1));
    expect(where.path).toBe("/admin/dashboard");
  });

  it("goes back to the list on a phone with one step back, not a second list entry", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query === "(max-width: 900px)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    try {
      await render("/admin/tickets/list?view=mine", ["/admin/dashboard"]);
      await act(async () => row(1047).querySelector<HTMLButtonElement>(".tickets-row-title")!.click());
      await settle();
      expect(host.querySelector(".tickets-queue--phone-detail")).not.toBeNull();
      await act(async () => button("← All tickets").click());
      await settle();
      expect(where.path).toBe("/admin/tickets/list?view=mine");
      await act(async () => go(-1));
      expect(where.path).toBe("/admin/dashboard");
    } finally {
      window.matchMedia = original;
    }
  });

  it("reads the open ticket again after a bulk action that included it", async () => {
    await render("/admin/tickets/list?ticket=47");
    const reads = () => calls.filter((c) => c.url.endsWith("/tickets/47") && c.method === "GET").length;
    expect(reads()).toBe(1);
    await act(async () => row(1042).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await act(async () => button("Close", host.querySelector(".tickets-bulkbar")!).click());
    await settle();
    expect(reads()).toBe(1);
    await act(async () => row(1047).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await act(async () => button("Close", host.querySelector(".tickets-bulkbar")!).click());
    await settle();
    expect(reads()).toBe(2);
  });

  it("empties the search box when the address drops the search", async () => {
    await render();
    const search = () => host.querySelector<HTMLInputElement>('input[aria-label="Search tickets"]')!;
    await type(search(), "ldap");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 350));
    });
    await settle();
    expect(where.path).toContain("q=ldap");
    await act(async () => go("/admin/tickets/list?view=needs_staff"));
    await settle();
    expect(search().value).toBe("");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 350));
    });
    await settle();
    expect(where.path).toBe("/admin/tickets/list?view=needs_staff");
  });

  it("does not show the last ticket's error while the next one loads", async () => {
    const base = fakeTicketsApi(calls, (url) =>
      url.endsWith("/tickets/99") ? new Response(JSON.stringify({ detail: "Ticket not found." }), { status: 404 }) : undefined,
    );
    vi.mocked(authFetch).mockImplementation(((url: string, init?: RequestInit) =>
      url.endsWith("/tickets/47") ? new Promise(() => undefined) : base(url, init)) as typeof authFetch);
    await render("/admin/tickets/list?ticket=99");
    expect(panel().textContent).toContain("Ticket not found.");
    await act(async () => row(1047).querySelector<HTMLButtonElement>(".tickets-row-title")!.click());
    await settle();
    expect(panel().textContent).toContain("Loading the ticket…");
    expect(panel().textContent).not.toContain("Ticket not found.");
  });

  it("stops two quick image picks from passing the limit together", async () => {
    await render("/admin/tickets/list?ticket=47");
    const input = panel().querySelector<HTMLInputElement>('input[type="file"]')!;
    const pick = (names: string[]) => {
      Object.defineProperty(input, "files", {
        value: names.map((n) => new File([new Uint8Array(10)], n, { type: "image/png" })),
        configurable: true,
      });
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    await act(async () => {
      pick(["1.png", "2.png", "3.png"]);
      pick(["4.png", "5.png", "6.png"]);
    });
    await settle();
    expect(panel().querySelectorAll(".tickets-thumb")).toHaveLength(5);
    expect(panel().textContent).toContain("6.png: at most 5 images per message");
  });

  it("says the delete filter leaves out the search and the quick view", async () => {
    await render("/admin/tickets/list?view=needs_staff&q=ldap");
    await act(async () => button("Delete by filter…").click());
    await settle();
    expect(document.querySelector('[data-testid="tickets-delete-scope"]')!.textContent).toContain(
      "The search and the quick view are not part of this filter",
    );
  });

  it("marks the open row without aria-selected and names the unread dot", async () => {
    await render("/admin/tickets/list?ticket=47");
    expect(host.querySelector("tr[aria-selected]")).toBeNull();
    expect(row(1047).querySelector(".tickets-row-title")!.getAttribute("aria-current")).toBe("true");
    expect(row(1042).querySelector(".tickets-row-title")!.hasAttribute("aria-current")).toBe(false);
    expect(row(1047).querySelector(".tickets-unread-dot")!.getAttribute("role")).toBe("img");
    expect(row(1047).querySelector(".tickets-row-sub bdi")!.textContent).toBe("Reza Ahmadi");
  });

  it("gives the focus back to the assignee button when the picker closes", async () => {
    await render("/admin/tickets/list?ticket=47");
    const trigger = panel().querySelector<HTMLButtonElement>(".tickets-assignee__btn")!;
    await act(async () => trigger.click());
    const pop = panel().querySelector<HTMLElement>(".tickets-assign-pop")!;
    expect(pop.querySelector('[role="listbox"], [role="option"]')).toBeNull();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(panel().querySelector(".tickets-assign-pop")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("who may change what", () => {
  it("lets a read-only account see everything and change nothing", async () => {
    readOnly.value = true;
    useApi((url) => (url.endsWith("/meta") ? makeMeta({ can_write: false, is_super_admin: false }) : undefined));
    await render("/admin/tickets/list?ticket=47");
    expect(host.querySelector('tbody input[type="checkbox"]')).toBeNull();
    expect(button("Assign to me")).toBeUndefined();
    expect(button("Delete by filter…")).toBeUndefined();
    expect(button("Export CSV")).toBeDefined();
    expect(panel().querySelector(".tickets-composer")).toBeNull();
    expect([...panel().querySelectorAll<HTMLSelectElement>("select")].every((s) => s.disabled)).toBe(true);
    expect(panel().querySelector<HTMLButtonElement>(".tickets-assignee__btn")!.disabled).toBe(true);
    expect(panel().textContent).toContain("You can read this ticket.");
  });

  it("gives the Support role the work but no deletes", async () => {
    useApi((url) => (url.endsWith("/meta") ? makeMeta({ is_super_admin: false }) : undefined));
    await render("/admin/tickets/list?ticket=47");
    expect(button("Delete by filter…")).toBeUndefined();
    expect(button("Delete…", panel())).toBeUndefined();
    expect(panel().querySelector(".tickets-composer")).not.toBeNull();
    await act(async () => row(1047).querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    const bar = host.querySelector<HTMLElement>(".tickets-bulkbar")!;
    expect(button("Close", bar)).toBeDefined();
    expect(button("Delete…", bar)).toBeUndefined();
  });
});
