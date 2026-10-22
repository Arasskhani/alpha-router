/**
 * @vitest-environment happy-dom
 *
 * Support (the person's side): the list and its filter, a new ticket (the form
 * fields it sends, images refused before sending and by the server), the
 * conversation (thread, auto-close notice, reply, mark resolved), every
 * refusal the API can answer with, and Support switched off.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ authFetch: vi.fn() }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch } from "../../api";
import { TICKETS_CHANGED_EVENT, type SupportStatus, type UserTicketDetail, type UserTicketList } from "../../lib/tickets";
import Support from "./Support";

const DAY = 86_400_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString().replace(/\.\d+Z$/, "Z");

const STATUS: SupportStatus = {
  enabled: true,
  unread: 1,
  categories: ["Bug", "Problem", "Question"],
  priorities: ["low", "normal", "high", "urgent"],
  limits: { image_types: ["png", "jpg", "webp", "gif"], max_image_mb: 5, max_images: 5, max_side_px: 4096 },
  reopen_days: 14,
  auto_close_days: 7,
  reporter: { name: "Sara Karimi", username: "s.karimi", email: "s.karimi@company.ir", department: "Finance" },
};

const SUMMARY = {
  id: 1042,
  number: 1042,
  title: "Image generation fails with Gemini",
  category: "Bug",
  priority: "high" as const,
  status: "waiting" as const,
  user_unread: true,
  created_at: iso(-3_600_000),
  updated_at: iso(-25 * 60_000),
  message_count: 3,
  image_count: 1,
  reopen_until: null,
};

const LIST: UserTicketList = {
  counts: { open: 2, resolved: 5, all: 7 },
  items: [
    SUMMARY,
    {
      ...SUMMARY,
      id: 1021,
      number: 1021,
      title: "Add a shortcut to switch models",
      category: "Feature request",
      priority: "low",
      status: "resolved",
      user_unread: false,
      updated_at: iso(-3 * DAY),
      image_count: 0,
      reopen_until: iso(11 * DAY - 60_000),
    },
  ],
};

const DETAIL: UserTicketDetail = {
  ...SUMMARY,
  user_unread: false,
  reporter: STATUS.reporter,
  assignee: { id: 2, name: "Majid Arasskhani" },
  auto_close_at: iso(7 * DAY - 60_000),
  can_reply: true,
  can_resolve: true,
  messages: [
    {
      id: 1,
      kind: "user",
      author: { id: 5, name: "Sara Karimi" },
      author_label: "You",
      body: "Every image request ends with 502.",
      created_at: iso(-3_600_000),
      internal: false,
      attachments: [
        { id: 7, url: "/api/support/attachments/7", mime: "image/png", bytes: 412_000, width: 800, height: 500, display_name: "error.png" },
      ],
    },
    {
      id: 2,
      kind: "auto",
      author: null,
      author_label: "Automatic reply",
      body: "Hello Sara, we have your ticket #1042.",
      created_at: iso(-3_600_000),
      internal: false,
      attachments: [],
    },
    {
      id: 3,
      kind: "event",
      author: null,
      author_label: "",
      body: "Majid Arasskhani is handling your ticket",
      created_at: iso(-2_000_000),
      internal: false,
      attachments: [],
    },
    {
      id: 4,
      kind: "staff",
      author: { id: 2, name: "Majid Arasskhani" },
      author_label: "Administrator",
      body: "Could you try once more?",
      created_at: iso(-1_500_000),
      internal: false,
      attachments: [],
    },
  ],
};

type Call = { url: string; method: string; body: BodyInit | null | undefined };
type Handler = (url: string, method: string, body: BodyInit | null | undefined) => Response | undefined;

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
let handler: Handler;
let announced: number;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const refusal = (status: number, detail: unknown) => json({ detail }, status);

function defaults(url: string, method: string): Response {
  if (url === "/api/support/status") return json(STATUS);
  if (url.startsWith("/api/support/tickets?")) return json(LIST);
  if (url === "/api/support/tickets/1042" && method === "GET") return json(DETAIL);
  return json({});
}

const onAnnounce = () => {
  announced += 1;
};

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  announced = 0;
  handler = () => undefined;
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: init.body });
    return handler(url, method, init.body) ?? defaults(url, method);
  });
  if (!URL.createObjectURL) {
    Object.assign(URL, { createObjectURL: () => "blob:preview", revokeObjectURL: () => undefined });
  }
  window.addEventListener(TICKETS_CHANGED_EVENT, onAnnounce);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.removeEventListener(TICKETS_CHANGED_EVENT, onAnnounce);
  vi.useRealTimers();
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

async function render(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app/support" element={<Support />} />
          <Route path="/app/support/:ticketId" element={<Support />} />
        </Routes>
        <Where />
      </MemoryRouter>,
    );
  });
  await settle();
}

async function settle() {
  for (let i = 0; i < 4; i += 1) await act(async () => undefined);
}

const text = () => document.body.textContent ?? "";
const where = () => document.querySelector('[data-testid="where"]')?.textContent;
const button = (name: string | RegExp) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof name === "string" ? b.textContent?.trim() === name : name.test(b.textContent ?? ""),
  );
const byLabel = <T extends HTMLElement>(label: string) => {
  const el = [...document.querySelectorAll("label")].find((l) => l.textContent?.replace("*", "").trim() === label);
  return document.getElementById(el?.htmlFor ?? "") as T;
};

async function click(el: Element | null | undefined) {
  expect(el, "element to click").toBeTruthy();
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function pickFiles(testId: string, files: File[]) {
  const input = document.querySelector<HTMLInputElement>(`[data-testid="${testId}"]`)!;
  expect(input).toBeTruthy();
  await act(async () => {
    Object.defineProperty(input, "files", { value: files, configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

const png = (name = "error.png", bytes = 1000) => new File([new Uint8Array(bytes)], name, { type: "image/png" });

describe("the Support list", () => {
  it("shows the person's tickets with their badges, counts and a New reply marker", async () => {
    await render("/app/support");
    expect(calls.map((c) => c.url)).toContain("/api/support/tickets?state=open");
    expect(button(/^Open · 2$/)?.getAttribute("aria-pressed")).toBe("true");
    expect(button(/^Resolved · 5$/)).toBeTruthy();
    expect(button("All")).toBeTruthy();

    const rows = [...document.querySelectorAll<HTMLAnchorElement>(".support-list a")];
    expect(rows.map((a) => a.getAttribute("href"))).toEqual(["/app/support/1042", "/app/support/1021"]);
    expect(rows[0].className).toContain("support-item--unread");
    expect(rows[0].textContent).toContain("#1042");
    expect(rows[0].textContent).toContain("New reply");
    expect(rows[0].textContent).toContain("Waiting for you");
    expect(rows[0].textContent).toContain("High");
    expect(rows[0].textContent).toContain("Updated 25 min ago · 3 messages · 1 image");
    expect(rows[0].querySelector(".support-item__text")?.getAttribute("dir")).toBe("auto");
    expect(rows[1].textContent).not.toContain("New reply");
    expect(rows[1].textContent).toContain("Resolved 3 days ago · can be reopened for 11 days");
  });

  it("asks for another state and searches after a pause", async () => {
    await render("/app/support");
    await click(button(/^Resolved/));
    expect(calls.at(-1)?.url).toBe("/api/support/tickets?state=resolved");
    expect(button(/^Resolved/)?.getAttribute("aria-pressed")).toBe("true");

    await type(document.querySelector<HTMLInputElement>('input[type="search"]')!, "gemini");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });
    await settle();
    expect(calls.at(-1)?.url).toBe("/api/support/tickets?state=resolved&q=gemini");
  });

  it("says so when nothing is open", async () => {
    handler = (url) => (url.startsWith("/api/support/tickets?") ? json({ items: [], counts: { open: 0, resolved: 0, all: 0 } }) : undefined);
    await render("/app/support");
    expect(text()).toContain("No open tickets.");
  });

  it("leaves out New ticket for an inactive account", async () => {
    readOnly.value = true;
    await render("/app/support");
    expect(button("+ New ticket")).toBeUndefined();
    expect(document.querySelectorAll(".support-list a")).toHaveLength(2);
  });
});

describe("a new ticket", () => {
  async function openForm() {
    await render("/app/support");
    await click(button("+ New ticket"));
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
  }

  it("shows the reporter and sends the contract's multipart fields", async () => {
    handler = (url, method) => (url === "/api/support/tickets" && method === "POST" ? json(DETAIL, 201) : undefined);
    await openForm();
    expect(text()).toContain("Sent as Sara Karimi · s.karimi@company.ir · Finance");
    const submit = button("Submit ticket")!;
    expect(submit.disabled).toBe(true);

    await type(byLabel<HTMLInputElement>("Title"), "Image generation fails");
    expect(text()).toContain("22 / 150");
    await type(byLabel<HTMLTextAreaElement>("Description"), "Every request ends with 502.");
    expect(text()).toContain("28 / 5000");
    const category = byLabel<HTMLSelectElement>("Category");
    await act(async () => {
      category.value = "Problem";
      category.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await click(button("Urgent"));
    expect(button("Urgent")?.getAttribute("aria-pressed")).toBe("true");
    await pickFiles("support-new-files", [png("error.png"), png("photo.JPEG")]);
    expect(document.querySelectorAll(".support-thumb:not(.support-thumb--refused)")).toHaveLength(2);

    await click(button("Submit ticket"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/support/tickets");
    const form = post.body as FormData;
    expect(form.get("title")).toBe("Image generation fails");
    expect(form.get("description")).toBe("Every request ends with 502.");
    expect(form.get("category")).toBe("Problem");
    expect(form.get("priority")).toBe("urgent");
    expect((form.getAll("images") as File[]).map((f) => f.name)).toEqual(["error.png", "photo.JPEG"]);
    const context = JSON.parse(String(form.get("context")));
    expect(Object.keys(context).sort()).toEqual(["browser", "page"]);
    expect(context.browser.length).toBeLessThanOrEqual(200);
    expect(where()).toBe("/app/support/1042");
    expect(announced).toBeGreaterThan(0);
  });

  it("sends no context when technical details are unticked", async () => {
    handler = (url, method) => (url === "/api/support/tickets" && method === "POST" ? json(DETAIL, 201) : undefined);
    await openForm();
    await type(byLabel<HTMLInputElement>("Title"), "T");
    await type(byLabel<HTMLTextAreaElement>("Description"), "D");
    const box = document.querySelector<HTMLInputElement>('.support-check input[type="checkbox"]')!;
    expect(box.checked).toBe(true);
    await click(box);
    await click(button("Submit ticket"));
    const form = calls.find((c) => c.method === "POST")!.body as FormData;
    expect(form.has("context")).toBe(false);
    expect(form.getAll("images")).toEqual([]);
  });

  it("refuses an SVG and an oversized image before sending, and stops at the image limit", async () => {
    await openForm();
    await pickFiles("support-new-files", [
      png("ok.png"),
      new File(["<svg/>"], "logo.svg", { type: "image/svg+xml" }),
      png("huge.png", 5 * 1024 * 1024 + 1),
    ]);
    const kept = [...document.querySelectorAll(".support-thumb:not(.support-thumb--refused)")];
    const refused = [...document.querySelectorAll(".support-thumb--refused")].map((el) => el.textContent);
    expect(kept.map((el) => el.textContent)).toEqual([expect.stringContaining("ok.png")]);
    expect(refused).toEqual([expect.stringContaining("not allowed"), expect.stringContaining("over 5 MB")]);
    expect(refused[0]).toContain("logo.svg");
    expect(refused[1]).toContain("huge.png");

    await pickFiles("support-new-files", [png("2.png"), png("3.png"), png("4.png"), png("5.png"), png("6.png")]);
    expect(document.querySelectorAll(".support-thumb:not(.support-thumb--refused)")).toHaveLength(5);
    expect(document.querySelector(".support-thumb--refused")?.textContent).toContain("5 images at most");

    await click(document.querySelector('[aria-label="Remove ok.png"]'));
    expect(document.querySelectorAll(".support-thumb:not(.support-thumb--refused)")).toHaveLength(4);
  });

  it("names the image the server refused and marks it", async () => {
    handler = (url, method) =>
      url === "/api/support/tickets" && method === "POST"
        ? refusal(422, { code: "image_rejected", message: "This file is not a readable image.", file: "error.png" })
        : undefined;
    await openForm();
    await type(byLabel<HTMLInputElement>("Title"), "T");
    await type(byLabel<HTMLTextAreaElement>("Description"), "D");
    await pickFiles("support-new-files", [png("error.png")]);
    await click(button("Submit ticket"));
    expect(document.querySelector('[role="alert"]')?.textContent).toBe(
      "“error.png” was not accepted: This file is not a readable image.",
    );
    expect(document.querySelector(".support-thumb--refused")?.textContent).toContain("error.png");
    expect(document.querySelectorAll(".support-thumb:not(.support-thumb--refused)")).toHaveLength(0);
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
  });

  it.each([
    [429, { code: "ticket_rate_limited", message: "x" }, "several tickets in the last hour"],
    [409, { code: "too_many_open", message: "x" }, "most open tickets allowed"],
    [422, { code: "invalid_category", message: "x" }, "category is no longer offered"],
    [413, "Request Entity Too Large", "larger than 5 MB"],
  ])("explains a %i refusal", async (status, detail, words) => {
    handler = (url, method) => (url === "/api/support/tickets" && method === "POST" ? refusal(status, detail) : undefined);
    await openForm();
    await type(byLabel<HTMLInputElement>("Title"), "T");
    await type(byLabel<HTMLTextAreaElement>("Description"), "D");
    await click(button("Submit ticket"));
    expect(document.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain(words);
  });

  it("opens from ?new=1, the link a closed conversation offers", async () => {
    await render("/app/support?new=1");
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    await click(button("Cancel"));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(where()).toBe("/app/support");
  });
});

describe("the conversation", () => {
  it("shows the thread, the images and the auto-close notice, and clears the count", async () => {
    await render("/app/support/1042");
    expect(calls.map((c) => c.url)).toContain("/api/support/tickets/1042");
    expect(announced).toBe(1);
    expect(document.querySelector(".support-head")?.textContent).toContain("#1042");
    expect(document.querySelector(".support-head")?.textContent).toContain("Waiting for you");

    const items = [...document.querySelectorAll(".support-thread > li")];
    expect(items.map((li) => li.className)).toEqual([
      "support-msg support-msg--user",
      "support-msg support-msg--auto",
      "support-event",
      "support-msg support-msg--staff",
    ]);
    expect(items[0].textContent).toContain("Sara Karimi");
    expect(items[0].textContent).toContain("You");
    expect(items[1].textContent).toContain("Support team");
    expect(items[1].textContent).toContain("Automatic reply");
    expect(items[3].textContent).toContain("Administrator");
    expect(items[3].querySelector(".support-msg__text")?.getAttribute("dir")).toBe("auto");

    const thumb = items[0].querySelector("img")!;
    expect(thumb.getAttribute("src")).toBe("/api/support/attachments/7");
    await click(items[0].querySelector(".support-msg__img"));
    expect(document.querySelector(".support-viewer img")?.getAttribute("src")).toBe("/api/support/attachments/7");

    const notice = document.querySelector(".support-autoclose")?.textContent ?? "";
    expect(notice).toContain("closes automatically on");
    expect(notice).toContain("(7 days)");
    expect(notice).toContain("You can reopen it for 14 days after that.");
  });

  it("sends a reply with its images and shows the ticket the server returns", async () => {
    const after: UserTicketDetail = {
      ...DETAIL,
      status: "open",
      auto_close_at: null,
      messages: [
        ...DETAIL.messages,
        { id: 9, kind: "user", author: { id: 5, name: "Sara Karimi" }, author_label: "You", body: "Still broken.", created_at: iso(0), internal: false, attachments: [] },
      ],
    };
    handler = (url, method) => (url === "/api/support/tickets/1042/messages" && method === "POST" ? json(after) : undefined);
    await render("/app/support/1042");
    const box = document.querySelector<HTMLTextAreaElement>(".support-composer textarea")!;
    expect(box.placeholder).toContain("sets the ticket back to Open");
    expect(button("Send reply")?.disabled).toBe(true);
    await type(box, "Still broken.");
    await pickFiles("support-reply-files", [png("again.png"), new File(["x"], "notes.pdf", { type: "application/pdf" })]);
    expect(document.querySelector(".support-thumb--refused")?.textContent).toContain("not allowed");
    const before = announced;
    await click(button("Send reply"));

    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/support/tickets/1042/messages");
    const form = post.body as FormData;
    expect(form.get("body")).toBe("Still broken.");
    expect((form.getAll("images") as File[]).map((f) => f.name)).toEqual(["again.png"]);
    expect(document.querySelectorAll(".support-thread > li")).toHaveLength(5);
    expect(document.querySelector(".support-autoclose")).toBeNull();
    expect(document.querySelector<HTMLTextAreaElement>(".support-composer textarea")!.value).toBe("");
    expect(announced).toBeGreaterThan(before);
  });

  it("marks the ticket resolved", async () => {
    const resolved: UserTicketDetail = {
      ...DETAIL,
      status: "resolved",
      auto_close_at: null,
      can_resolve: false,
      reopen_until: iso(14 * DAY),
    };
    handler = (url, method) => (url === "/api/support/tickets/1042/resolve" && method === "POST" ? json(resolved) : undefined);
    await render("/app/support/1042");
    await click(button("It works — mark resolved"));
    expect(calls.some((c) => c.url === "/api/support/tickets/1042/resolve" && c.method === "POST")).toBe(true);
    expect(document.querySelector(".support-head")?.textContent).toContain("Resolved");
    expect(button("It works — mark resolved")).toBeUndefined();
    expect(text()).toContain("This ticket is resolved. If the problem comes back, reply before");
    expect(document.querySelector<HTMLTextAreaElement>(".support-composer textarea")!.placeholder).toContain(
      "reopens the ticket",
    );
  });

  it("explains a reply after the reopen window and shows the ticket as it now is", async () => {
    let closed = false;
    handler = (url, method) => {
      if (url === "/api/support/tickets/1042/messages" && method === "POST") {
        closed = true;
        return refusal(409, { code: "reopen_window_passed", message: "x" });
      }
      if (url === "/api/support/tickets/1042" && closed) {
        return json({ ...DETAIL, status: "closed", can_reply: false, can_resolve: false, auto_close_at: null });
      }
      return undefined;
    };
    await render("/app/support/1042");
    await type(document.querySelector<HTMLTextAreaElement>(".support-composer textarea")!, "Hello?");
    await click(button("Send reply"));
    expect(document.querySelector(".support-alert")?.textContent).toContain("can no longer be reopened");
    expect(document.querySelector(".support-composer")).toBeNull();
    expect(text()).toContain("This ticket is closed and can no longer be reopened.");
    expect(document.querySelector('a[href="/app/support?new=1"]')).toBeTruthy();
  });

  it("lets an inactive account read but not reply", async () => {
    readOnly.value = true;
    await render("/app/support/1042");
    expect(document.querySelectorAll(".support-thread > li")).toHaveLength(4);
    expect(document.querySelector(".support-composer")).toBeNull();
    expect(text()).toContain("Your account is inactive: you can read this ticket, but not reply to it.");
  });

  it("says when the ticket is not there", async () => {
    handler = (url) => (url === "/api/support/tickets/1042" ? refusal(404, "Not found") : undefined);
    await render("/app/support/1042");
    expect(document.querySelector('[role="alert"]')?.textContent).toBe("This ticket was not found.");
    expect(announced).toBe(0);
  });
});

describe("Support switched off", () => {
  it("shows a calm page when /status says it is off", async () => {
    handler = (url) => (url === "/api/support/status" ? json({ ...STATUS, enabled: false }) : undefined);
    await render("/app/support");
    expect(text()).toContain("Support is turned off by your administrator");
    expect(calls.map((c) => c.url)).toEqual(["/api/support/status"]);
    expect(document.querySelector(".alert-error")).toBeNull();
  });

  it("shows it too when a later call answers tickets_disabled", async () => {
    handler = (url) =>
      url === "/api/support/tickets/1042"
        ? refusal(403, { code: "tickets_disabled", message: "Support is turned off." })
        : undefined;
    await render("/app/support/1042");
    expect(text()).toContain("Support is turned off by your administrator");
    expect(document.querySelector(".support-thread")).toBeNull();
  });
});
