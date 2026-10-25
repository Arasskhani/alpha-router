/**
 * @vitest-environment happy-dom
 *
 * Review & send: the draft read live from the server, Send with the change key
 * read, a draft changed in Outlook read again with a notice, Discard only after
 * a confirmation, Send disabled when sending is off, and every refusal the API
 * answers with (password needed, not connected, not found, a failed send).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ authFetch: vi.fn() }));
const dialogs = vi.hoisted(() => ({
  confirm: vi.fn(async () => true as boolean | "secondary"),
  prompt: vi.fn(async () => null as string | null),
}));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => dialogs }));

import { authFetch } from "../api";
import type { MailDraft, MailDraftCard, MailDraftLive } from "../lib/exchangeMail";
import MailReviewDialog, { CONFLICT_NOTICE, SEND_OFF_NOTICE } from "./MailReviewDialog";

const CARD: MailDraftCard = {
  id: 12,
  mailbox: "s.karimi@corp.example",
  kind: "reply",
  subject: "Re: Budget 1405",
  to: [{ name: "Ali Rezaei", email: "a.rezaei@corp.example" }],
  cc: [],
  preview: "Hello Ali,",
};

const LIVE: MailDraftLive = {
  id: 12,
  mailbox: "s.karimi@corp.example",
  kind: "reply",
  status: "draft",
  subject: "Re: Budget 1405",
  to: [{ name: "Ali Rezaei", email: "a.rezaei@corp.example" }],
  cc: [{ name: "", email: "finance@corp.example" }],
  body_preview: "Hello Ali,",
  created_at: "2026-10-25T08:00:00Z",
  sent_at: null,
  error: null,
  chat_session_id: "s-1",
  body_text: "Hello Ali,\n\nThe figures are attached.\n\nSara",
  change_key: "CK-1",
  owa_url: "https://mail.corp.example/owa/?ItemID=AAMk&exvsurl=1",
  can_send: true,
};

const SENT: MailDraft = {
  id: 12,
  mailbox: LIVE.mailbox,
  kind: "reply",
  status: "sent",
  subject: LIVE.subject,
  to: LIVE.to,
  cc: LIVE.cc,
  body_preview: LIVE.body_preview,
  created_at: LIVE.created_at,
  sent_at: "2026-10-25T08:05:00Z",
  error: null,
  chat_session_id: "s-1",
};

type Call = { url: string; method: string; body: unknown };
type Handler = (url: string, method: string, body: unknown) => Response | undefined;

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
let handler: Handler;
let onDraft: ReturnType<typeof vi.fn<(draft: MailDraft | MailDraftLive) => void>>;
let onClose: ReturnType<typeof vi.fn<() => void>>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const refusal = (status: number, code: string, message = "") => json({ detail: { code, message } }, status);

beforeEach(() => {
  dialogs.confirm.mockReset();
  dialogs.confirm.mockResolvedValue(true);
  calls = [];
  handler = () => undefined;
  onDraft = vi.fn<(draft: MailDraft | MailDraftLive) => void>();
  onClose = vi.fn<() => void>();
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    return handler(url, method, body) ?? (url === "/api/mail/drafts/12" ? json(LIVE) : json({}));
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

async function settle() {
  for (let i = 0; i < 5; i += 1) await act(async () => undefined);
}

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/app/chat"]}>
        <Routes>
          <Route path="*" element={<MailReviewDialog card={CARD} onDraft={onDraft} onClose={onClose} />} />
        </Routes>
        <Where />
      </MemoryRouter>,
    );
  });
  await settle();
}

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]');
const text = () => dialog()?.textContent ?? "";
const button = (name: string) =>
  [...(dialog()?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find((b) => b.textContent?.trim() === name);
const link = (name: string) =>
  [...(dialog()?.querySelectorAll<HTMLAnchorElement>("a") ?? [])].find((a) => a.textContent?.trim() === name);
const sends = () => calls.filter((c) => c.url === "/api/mail/drafts/12/send");
const reads = () => calls.filter((c) => c.url === "/api/mail/drafts/12" && c.method === "GET");

async function click(el: Element | null | undefined) {
  expect(el, "element to click").toBeTruthy();
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

describe("MailReviewDialog", () => {
  it("reads the draft live and shows who it is from and to, the subject and the full text", async () => {
    await render();
    expect(dialog()?.getAttribute("aria-label")).toBe("Review & send");
    expect(reads()).toHaveLength(1);
    const fields = [...dialog()!.querySelectorAll("dt")].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(fields).toEqual([
      ["From", "s.karimi@corp.example"],
      ["To", "Ali Rezaei <a.rezaei@corp.example>"],
      ["Cc", "finance@corp.example"],
      ["Subject", "Re: Budget 1405"],
    ]);
    const body = dialog()!.querySelector<HTMLElement>(".mail-review__text")!;
    expect(body.textContent).toBe(LIVE.body_text);
    expect(body.getAttribute("role")).toBe("region");
    expect(body.tabIndex).toBe(0);
    expect(button("Send")?.disabled).toBe(false);
    const outlook = link("Open in Outlook")!;
    expect(outlook.href).toBe(LIVE.owa_url);
    expect(outlook.target).toBe("_blank");
    expect(outlook.rel).toBe("noopener noreferrer");
    expect(onDraft).toHaveBeenCalledWith(LIVE);
    // Focus moved into the dialog.
    expect(dialog()!.contains(document.activeElement)).toBe(true);
  });

  it("says it is reading while the draft is on its way", async () => {
    let release: (r: Response) => void = () => undefined;
    vi.mocked(authFetch).mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)));
    await render();
    expect(text()).toContain("Reading the draft from your mailbox…");
    expect(button("Send")).toBeUndefined();
    await act(async () => release(json(LIVE)));
    await settle();
    expect(text()).not.toContain("Reading the draft");
    expect(button("Send")).toBeTruthy();
  });

  it("sends with the change key it read, and then says it was sent", async () => {
    let resolveSend: (r: Response) => void = () => undefined;
    vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? "GET").toUpperCase();
      calls.push({ url, method, body: typeof init.body === "string" ? JSON.parse(init.body) : undefined });
      if (url === "/api/mail/drafts/12/send") return new Promise<Response>((r) => (resolveSend = r));
      return json(LIVE);
    });
    await render();
    await click(button("Send"));
    expect(sends()).toEqual([{ url: "/api/mail/drafts/12/send", method: "POST", body: { change_key: "CK-1" } }]);
    // Disabled while sending, and so are Discard and Close.
    expect(button("Sending…")?.disabled).toBe(true);
    expect(button("Discard")?.disabled).toBe(true);
    expect(button("Close")?.disabled).toBe(true);
    await act(async () => resolveSend(json(SENT)));
    await settle();
    expect(text()).toContain("Sent");
    expect(text()).toContain("A copy is in Sent Items.");
    expect(button("Send")).toBeUndefined();
    expect(button("Discard")).toBeUndefined();
    expect(link("Open in Outlook")).toBeUndefined();
    expect(onDraft).toHaveBeenLastCalledWith(SENT);
  });

  it("reads a draft changed in Outlook again, with a notice, and sends the new change key", async () => {
    let read = 0;
    handler = (url, method) => {
      if (url === "/api/mail/drafts/12" && method === "GET") {
        read += 1;
        return json(read === 1 ? LIVE : { ...LIVE, body_text: "Hello Ali, edited in Outlook.", change_key: "CK-2" });
      }
      if (url === "/api/mail/drafts/12/send") {
        return sends().length === 1
          ? refusal(409, "exchange_conflict", "The draft changed in Exchange.")
          : json(SENT);
      }
      return undefined;
    };
    await render();
    await click(button("Send"));
    expect(reads()).toHaveLength(2);
    expect(text()).toContain(CONFLICT_NOTICE);
    expect(dialog()!.querySelector(".mail-review__text")?.textContent).toBe("Hello Ali, edited in Outlook.");
    expect(text()).not.toContain("Sent Items");
    await click(button("Send"));
    expect(sends().map((c) => c.body)).toEqual([{ change_key: "CK-1" }, { change_key: "CK-2" }]);
    expect(text()).toContain("A copy is in Sent Items.");
  });

  it("discards only after the person confirms", async () => {
    handler = (url) =>
      url === "/api/mail/drafts/12/discard" ? json({ ...SENT, status: "discarded", sent_at: null }) : undefined;
    await render();
    dialogs.confirm.mockResolvedValueOnce(false);
    await click(button("Discard"));
    expect(dialogs.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Discard this draft?", confirmLabel: "Discard", danger: true }),
    );
    expect(calls.some((c) => c.url.endsWith("/discard"))).toBe(false);
    expect(button("Send")).toBeTruthy();

    await click(button("Discard"));
    expect(calls.filter((c) => c.url === "/api/mail/drafts/12/discard" && c.method === "POST")).toHaveLength(1);
    expect(text()).toContain("This draft was discarded.");
    expect(button("Send")).toBeUndefined();
    expect(onDraft).toHaveBeenLastCalledWith(expect.objectContaining({ status: "discarded" }));
  });

  it("keeps Send disabled when sending is off, and says why", async () => {
    handler = (url) => (url === "/api/mail/drafts/12" ? json({ ...LIVE, can_send: false }) : undefined);
    await render();
    const send = button("Send")!;
    expect(send.disabled).toBe(true);
    expect(send.title).toBe(SEND_OFF_NOTICE);
    expect(text()).toContain(SEND_OFF_NOTICE);
    // Outlook is still a way to send it.
    expect(link("Open in Outlook")).toBeTruthy();
    await click(send);
    expect(sends()).toHaveLength(0);
  });

  it("turns Send off when the server says sending was switched off meanwhile", async () => {
    handler = (url) => (url === "/api/mail/drafts/12/send" ? refusal(403, "send_off", "Sending is off.") : undefined);
    await render();
    await click(button("Send"));
    expect(button("Send")?.disabled).toBe(true);
    expect(text()).toContain(SEND_OFF_NOTICE);
    expect(text().split(SEND_OFF_NOTICE)).toHaveLength(2);
  });

  it("shows a failed send as the server keeps it, with why", async () => {
    let read = 0;
    handler = (url, method) => {
      if (url === "/api/mail/drafts/12" && method === "GET") {
        read += 1;
        return read === 1 ? json(LIVE) : json({ ...SENT, status: "failed", sent_at: null, error: "You may not send as this mailbox." });
      }
      if (url === "/api/mail/drafts/12/send") {
        return refusal(403, "exchange_access_denied", "You may not send as this mailbox.");
      }
      return undefined;
    };
    await render();
    await click(button("Send"));
    expect(reads()).toHaveLength(2);
    expect(text()).toContain("The email was not sent: You may not send as this mailbox.");
    expect(button("Send")).toBeUndefined();
    // Still in Drafts: it can be opened in Outlook or discarded.
    expect(link("Open in Outlook")).toBeTruthy();
    expect(button("Discard")).toBeTruthy();
    expect(onDraft).toHaveBeenLastCalledWith(expect.objectContaining({ status: "failed" }));
  });

  it("says why a failed draft could not be discarded, and keeps Discard to try again", async () => {
    const failed = { ...SENT, status: "failed" as const, sent_at: null, error: "You may not send as this mailbox." };
    handler = (url, method) => {
      if (url === "/api/mail/drafts/12" && method === "GET") return json(failed);
      if (url === "/api/mail/drafts/12/discard") return refusal(502, "exchange_unreachable", "Exchange could not be reached.");
      return undefined;
    };
    await render();
    expect(text()).toContain("The email was not sent: You may not send as this mailbox.");
    await click(button("Discard"));
    expect(calls.filter((c) => c.url === "/api/mail/drafts/12/discard" && c.method === "POST")).toHaveLength(1);
    const alerts = [...dialog()!.querySelectorAll('[role="alert"]')].map((a) => a.textContent);
    expect(alerts).toContain("Exchange could not be reached.");
    expect(button("Discard")?.disabled).toBe(false);
  });

  it("does not repeat a failed send's error once the draft shows it", async () => {
    let read = 0;
    handler = (url, method) => {
      if (url === "/api/mail/drafts/12" && method === "GET") {
        read += 1;
        return read === 1 ? json(LIVE) : json({ ...SENT, status: "failed", sent_at: null, error: "You may not send as this mailbox." });
      }
      if (url === "/api/mail/drafts/12/send") return refusal(403, "exchange_access_denied", "You may not send as this mailbox.");
      return undefined;
    };
    await render();
    await click(button("Send"));
    expect(text().split("You may not send as this mailbox.")).toHaveLength(2);
  });

  it("says when too many emails were sent, without reading again", async () => {
    handler = (url) =>
      url === "/api/mail/drafts/12/send" ? refusal(429, "too_many_sends", "You sent 30 emails this hour.") : undefined;
    await render();
    await click(button("Send"));
    expect(text()).toContain("You sent 30 emails this hour.");
    expect(reads()).toHaveLength(1);
    expect(button("Send")?.disabled).toBe(false);
  });

  it("asks for the password in Connections when Exchange no longer accepts it", async () => {
    handler = (url) => (url === "/api/mail/drafts/12" ? refusal(409, "needs_password", "Password needed.") : undefined);
    await render();
    expect(text()).toContain("Exchange no longer accepts the saved password.");
    expect(button("Send")).toBeUndefined();
    expect(button("Try again")).toBeUndefined();
    await click(link("Open Connections"));
    expect(document.querySelector('[data-testid="where"]')?.textContent).toBe("/app/connections");
    expect(onClose).toHaveBeenCalled();
  });

  it("says the mailbox is not connected, and when a send finds the password refused", async () => {
    handler = (url) => (url === "/api/mail/drafts/12" ? refusal(404, "not_connected", "Not connected.") : undefined);
    await render();
    expect(text()).toContain("Your mailbox is not connected.");
    expect(link("Open Connections")).toBeTruthy();

    act(() => root.unmount());
    root = createRoot(host);
    handler = (url) => (url === "/api/mail/drafts/12/send" ? refusal(400, "exchange_auth", "Refused.") : undefined);
    await render();
    await click(button("Send"));
    expect(text()).toContain("Exchange no longer accepts the saved password.");
    expect(button("Send")).toBeUndefined();
  });

  it("says a draft that is not the person's was not found", async () => {
    handler = (url) => (url === "/api/mail/drafts/12" ? refusal(404, "not_found", "Not found.") : undefined);
    await render();
    expect(text()).toContain("This draft was not found.");
    expect(button("Try again")).toBeUndefined();
  });

  it("offers to try again when the mailbox could not be reached", async () => {
    let read = 0;
    handler = (url, method) => {
      if (url !== "/api/mail/drafts/12" || method !== "GET") return undefined;
      read += 1;
      return read === 1 ? refusal(502, "exchange_unreachable", "Exchange could not be reached.") : json(LIVE);
    };
    await render();
    expect(text()).toContain("Exchange could not be reached.");
    await click(button("Try again"));
    expect(reads()).toHaveLength(2);
    expect(text()).not.toContain("could not be reached");
    expect(button("Send")).toBeTruthy();
  });

  it("shows a draft no longer in Drafts as the server says", async () => {
    handler = (url) =>
      url === "/api/mail/drafts/12"
        ? json({ ...SENT, status: "discarded", sent_at: null, error: "The draft is no longer in Drafts: it was sent or deleted in Outlook." })
        : undefined;
    await render();
    expect(text()).toContain("The draft is no longer in Drafts: it was sent or deleted in Outlook.");
    expect(button("Send")).toBeUndefined();
    expect(button("Discard")).toBeUndefined();
  });

  it("closes with Close and with Escape", async () => {
    await render();
    await click(button("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
