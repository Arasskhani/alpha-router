/**
 * @vitest-environment happy-dom
 *
 * Admin › Tickets › Settings and the delete dialogs: the bounds are checked
 * before Save, Save sends the whole form, only a Super Admin changes or
 * deletes anything, the typed phrase gates a delete, and a changed count
 * deletes nothing and asks again.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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
import { fakeTicketsApi, makeMeta, type Call } from "../../components/tickets/testFixtures";
import Tickets from "./Tickets";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];

function useApi(override?: Parameters<typeof fakeTicketsApi>[1]) {
  vi.mocked(authFetch).mockImplementation(fakeTicketsApi(calls, override) as typeof authFetch);
}

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  dialogs.confirm.mockReset();
  dialogs.confirm.mockResolvedValue(true);
  dialogs.prompt.mockReset();
  dialogs.prompt.mockResolvedValue(null);
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

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/admin/tickets/settings"]}>
        <Routes>
          <Route path="/admin/tickets/settings" element={<Tickets />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await act(async () => undefined);
  await act(async () => undefined);
}

async function settle() {
  await act(async () => undefined);
  await act(async () => undefined);
}

const button = (text: string | RegExp) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof text === "string" ? b.textContent?.trim() === text : text.test(b.textContent ?? ""),
  )!;
const field = (label: string) =>
  [...host.querySelectorAll<HTMLLabelElement>("label.tickets-field")]
    .find((l) => l.textContent?.startsWith(label))!
    .querySelector<HTMLInputElement>("input, select")!;

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function press(el: HTMLElement, key: string) {
  await act(async () => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

describe("Tickets settings", () => {
  it("checks the bounds before saving and sends the whole form", async () => {
    await render();
    expect(field("Close tickets waiting for the user after").value).toBe("7");
    await type(field("Tickets a person may open per hour"), "0");
    expect(host.textContent).toContain("Enter a whole number from 1 to 100.");
    expect(button("Save settings").disabled).toBe(true);
    await type(field("Tickets a person may open per hour"), "8");
    await type(field("Largest side (px)"), "9000");
    expect(host.textContent).toContain("Enter a whole number from 512 to 8192.");
    await type(field("Largest side (px)"), "2048");

    const address = host.querySelector<HTMLInputElement>('input[aria-label="Add an address"]')!;
    await type(address, "not-an-address");
    await press(address, "Enter");
    expect(host.textContent).toContain("Not a valid address: not-an-address");
    await type(address, "it@company.ir");
    await press(address, "Enter");

    await act(async () => button("+ Add").click());
    const category = host.querySelector<HTMLInputElement>('input[aria-label="New category"]')!;
    await type(category, "Access");
    await press(category, "Enter");

    const emailUser = [...host.querySelectorAll("label.tickets-check")]
      .find((l) => l.textContent?.includes("Email the user"))!
      .querySelector<HTMLInputElement>("input")!;
    expect(emailUser.checked).toBe(false);
    expect(host.textContent).toContain("off: they see the number on Support in the app");
    await act(async () => emailUser.click());

    expect(button("Save settings").disabled).toBe(false);
    await act(async () => button("Save settings").click());
    await settle();
    const put = calls.find((c) => c.url.endsWith("/settings") && c.method === "PUT")!;
    expect(put.body).toMatchObject({
      per_hour: 8,
      max_side_px: 2048,
      email_user: true,
      notify_emails: ["support@company.ir", "it@company.ir"],
      categories: ["Bug", "Problem", "Question", "Feature request", "Access"],
      auto_close_days: 7,
    });
    expect(host.textContent).toContain("Settings saved.");
  });

  it("treats inner spaces in a category name as the server does", async () => {
    await render();
    await act(async () => button("+ Add").click());
    const category = host.querySelector<HTMLInputElement>('input[aria-label="New category"]')!;
    await type(category, "  feature   REQUEST ");
    await press(category, "Enter");
    expect(host.textContent).toContain("Each category needs a different name.");
    expect(button("Save settings").disabled).toBe(true);

    const added = button("feature REQUEST");
    expect(added).toBeDefined();
    await act(async () => added.click());
    const rename = host.querySelector<HTMLInputElement>('input[aria-label="Rename feature REQUEST"]')!;
    await type(rename, " Access \t  rights ");
    await press(rename, "Enter");
    expect(host.textContent).not.toContain("Each category needs a different name.");
    await act(async () => button("Save settings").click());
    await settle();
    const put = calls.find((c) => c.url.endsWith("/settings") && c.method === "PUT")!;
    expect((put.body as { categories: string[] }).categories.at(-1)).toBe("Access rights");
  });

  it("says why the settings are missing and reads them again on Try again", async () => {
    let fail = true;
    useApi((url, method) =>
      url.endsWith("/settings") && method === "GET" && fail
        ? new Response(JSON.stringify({ detail: "Database is busy." }), { status: 503 })
        : undefined,
    );
    await render();
    expect(host.textContent).not.toContain("Loading the settings…");
    expect(host.querySelector('[role="alert"]')!.textContent).toContain("The settings could not be read: Database is busy.");
    fail = false;
    await act(async () => button("Try again").click());
    await settle();
    expect(field("Close tickets waiting for the user after").value).toBe("7");
  });

  it("keeps at least one image type and one category", async () => {
    await render();
    for (const label of ["PNG", "JPG / JPEG", "WEBP", "GIF"]) {
      await act(async () => button(new RegExp(`^${label.replace("/", "\\/")}`)).click());
    }
    expect(host.textContent).toContain("Allow at least one image type.");
    expect(button("Save settings").disabled).toBe(true);
  });

  it("is read-only for anyone but a Super Admin", async () => {
    useApi((url) => (url.endsWith("/meta") ? makeMeta({ is_super_admin: false }) : undefined));
    await render();
    expect(host.textContent).toContain("Only a Super Admin can change these settings.");
    expect(field("Tickets a person may open per hour").disabled).toBe(true);
    expect(button("Save settings")).toBeUndefined();
    expect(button("Delete all tickets…")).toBeUndefined();
    expect(host.querySelector('input[aria-label="Add an address"]')).toBeNull();
  });

  it("is read-only for a Read Only Super Admin too", async () => {
    readOnly.value = true;
    await render();
    expect(button("Save settings")).toBeUndefined();
    expect(button("Delete by filter…")).toBeUndefined();
  });
});

describe("deleting tickets", () => {
  it("deletes by filter only with the exact phrase, and asks again when the count changed", async () => {
    let attempts = 0;
    let previews = 0;
    useApi((url, method, body) => {
      if (url.endsWith("/delete-preview")) {
        previews += 1;
        const count = previews === 1 ? 128 : 130;
        return { count, messages: 611, images: 342, image_bytes: 64_000_000, includes_active: false, token: `t${previews}`, phrase: `DELETE ${count} TICKETS` };
      }
      if (url.endsWith("/delete") && method === "POST") {
        attempts += 1;
        if (attempts === 1) {
          return new Response(JSON.stringify({ detail: { code: "count_changed", count: 130, message: "The count changed." } }), {
            status: 409,
          });
        }
        return { deleted: (body as { phrase: string }).phrase === "DELETE 130 TICKETS" ? 130 : 0, messages: 1, images: 1 };
      }
      return undefined;
    });
    await render();
    await act(async () => button("Delete by filter…").click());
    const dialog = () => document.querySelector<HTMLElement>(".tickets-modal")!;
    expect(dialog().textContent).toContain("Resolved");
    await act(async () => button("Count the tickets").click());
    await settle();
    const preview = calls.find((c) => c.url.endsWith("/delete-preview"))!;
    expect(preview.body).toEqual({ filter: { statuses: ["resolved", "closed"] } });
    expect(dialog().querySelector('[data-testid="tickets-delete-impact"]')!.textContent).toBe(
      "128 tickets · 611 messages · 342 images (61.0 MB) will be deleted for good.",
    );
    expect(dialog().textContent).toContain("Export these 128 tickets as CSV first");
    expect(dialog().textContent).toContain("Open, In progress and Waiting tickets are not in this filter.");

    const phrase = dialog().querySelector<HTMLInputElement>('input[aria-label="Type DELETE 128 TICKETS to confirm"]')!;
    expect(button("Delete 128 tickets").disabled).toBe(true);
    await type(phrase, "delete 128 tickets");
    expect(button("Delete 128 tickets").disabled).toBe(true);
    await type(phrase, "DELETE 128 TICKETS");
    expect(button("Delete 128 tickets").disabled).toBe(false);
    await act(async () => button("Delete 128 tickets").click());
    await settle();

    const first = calls.find((c) => c.url.endsWith("/delete") && c.method === "POST")!;
    expect(first.body).toEqual({ filter: { statuses: ["resolved", "closed"] }, token: "t1", phrase: "DELETE 128 TICKETS" });
    expect(dialog().textContent).toContain("There are now 130 tickets (it was 128)");
    expect(button("Delete 130 tickets").disabled).toBe(true);
    const again = dialog().querySelector<HTMLInputElement>('input[aria-label="Type DELETE 130 TICKETS to confirm"]')!;
    expect(again.value).toBe("");
    await type(again, "DELETE 130 TICKETS");
    await act(async () => button("Delete 130 tickets").click());
    await settle();
    expect(calls.filter((c) => c.url.endsWith("/delete")).at(-1)!.body).toMatchObject({ token: "t2", phrase: "DELETE 130 TICKETS" });
    expect(document.querySelector(".tickets-modal")).toBeNull();
    expect(host.textContent).toContain("130 tickets were deleted.");
  });

  it("deletes everything after two dialogs and the typed phrase, and nothing when stopped", async () => {
    await render();
    await act(async () => button("Delete all tickets…").click());
    await settle();
    expect(dialogs.confirm).toHaveBeenCalledTimes(2);
    expect(dialogs.prompt).toHaveBeenCalledWith(expect.objectContaining({ promptExactMatch: "DELETE ALL TICKETS" }));
    expect(calls.some((c) => c.url.endsWith("/delete-all"))).toBe(false);

    dialogs.prompt.mockResolvedValue("DELETE ALL TICKETS");
    await act(async () => button("Delete all tickets…").click());
    await settle();
    expect(calls.find((c) => c.url.endsWith("/delete-all"))!.body).toEqual({ phrase: "DELETE ALL TICKETS" });
    expect(host.textContent).toContain("300 tickets were deleted.");
  });
});
