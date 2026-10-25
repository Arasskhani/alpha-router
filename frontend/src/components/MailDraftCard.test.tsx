/**
 * @vitest-environment happy-dom
 *
 * A draft card under an answer: what it shows (kind, subject, To, preview),
 * that it asks nothing of the server until Review & send is pressed, and that
 * what the dialog learns (sent, failed, the Outlook link) stays on the card,
 * also when the card is drawn again.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ authFetch: vi.fn() }));
vi.mock("../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), prompt: vi.fn(async () => null) }),
}));

import { authFetch } from "../api";
import type { MailDraftCard as Card } from "../lib/exchangeMail";
import MailDraftCard, { MailDraftCardList } from "./MailDraftCard";

const CARD: Card = {
  id: 12,
  mailbox: "s.karimi@corp.example",
  kind: "reply",
  subject: "Re: Budget 1405",
  to: [
    { name: "Ali Rezaei", email: "a.rezaei@corp.example" },
    { name: "", email: "finance@corp.example" },
  ],
  cc: [],
  preview: "Hello Ali,\nThe figures are attached.",
};

const LIVE = {
  ...CARD,
  status: "draft",
  body_preview: CARD.preview,
  created_at: "2026-10-25T08:00:00Z",
  sent_at: null,
  error: null,
  chat_session_id: "s-1",
  body_text: "Hello Ali,\nThe figures are attached.",
  change_key: "CK-1",
  owa_url: "https://mail.corp.example/owa/?ItemID=AAMk",
  can_send: true,
};

let host: HTMLDivElement;
let root: Root;
let urls: string[];
let responses: Record<string, () => Response>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  sessionStorage.clear();
  urls = [];
  responses = {
    "GET /api/mail/drafts/12": () => json(LIVE),
    "POST /api/mail/drafts/12/send": () => json({ ...LIVE, status: "sent", sent_at: "2026-10-25T08:05:00Z" }),
  };
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
    const key = `${(init.method ?? "GET").toUpperCase()} ${url}`;
    urls.push(key);
    return responses[key]?.() ?? json({});
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

async function settle() {
  for (let i = 0; i < 5; i += 1) await act(async () => undefined);
}

async function render(node: React.ReactNode) {
  await act(async () => root.render(<MemoryRouter>{node}</MemoryRouter>));
  await settle();
}

const card = () => host.querySelector<HTMLElement>(".mail-draft-card")!;
const button = (name: string, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === name);
const link = (name: string, scope: ParentNode = host) =>
  [...scope.querySelectorAll<HTMLAnchorElement>("a")].find((a) => a.textContent?.trim() === name);

async function click(el: Element | null | undefined) {
  expect(el, "element to click").toBeTruthy();
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

describe("MailDraftCard", () => {
  it("shows the kind, subject, recipients and how it begins, and asks the server nothing", async () => {
    await render(<MailDraftCard card={CARD} />);
    expect(card().getAttribute("aria-label")).toBe("Draft reply: Re: Budget 1405");
    expect(card().querySelector(".mail-draft-card__kind")?.textContent).toBe("Draft reply");
    expect(card().querySelector(".mail-draft-card__subject")?.textContent).toBe("Re: Budget 1405");
    expect(card().querySelector(".mail-draft-card__to")?.textContent).toBe("To Ali Rezaei, finance@corp.example");
    expect(card().querySelector(".mail-draft-card__preview")?.textContent).toBe(CARD.preview);
    expect(card().querySelector("svg")).toBeTruthy();
    expect(button("Review & send", card())).toBeTruthy();
    // The Outlook link is not known until the dialog reads the draft.
    expect(link("Open in Outlook")).toBeUndefined();
    expect(urls).toEqual([]);
  });

  it("names each kind of draft", async () => {
    await render(
      <MailDraftCardList
        cards={[
          { ...CARD, id: 1, kind: "new" },
          { ...CARD, id: 2, kind: "reply_all" },
          { ...CARD, id: 3, kind: "forward", subject: "  " },
        ]}
      />,
    );
    const kinds = [...host.querySelectorAll(".mail-draft-card__kind")].map((k) => k.textContent);
    expect(kinds).toEqual(["Draft", "Draft reply all", "Draft forward"]);
    expect(host.querySelectorAll(".mail-draft-card__subject")[2].textContent).toBe("(no subject)");
  });

  it("opens Review & send, learns the Outlook link, and says Sent after sending, also when drawn again", async () => {
    await render(<MailDraftCard card={CARD} />);
    await click(button("Review & send", card()));
    expect(urls).toEqual(["GET /api/mail/drafts/12"]);
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    expect(link("Open in Outlook")?.href).toBe(LIVE.owa_url);

    await click(button("Send", document.querySelector('[role="dialog"]')!));
    expect(card().querySelector(".mail-draft-card__status")?.textContent).toBe("Sent");
    expect(button("Review & send", card())).toBeUndefined();
    await click(button("Close", document.querySelector('[role="dialog"]')!));
    expect(document.querySelector('[role="dialog"]')).toBeNull();

    // A reopened chat draws the card again: it still says Sent, and asks nothing.
    act(() => root.unmount());
    root = createRoot(host);
    urls = [];
    await render(<MailDraftCard card={CARD} />);
    expect(card().querySelector(".mail-draft-card__status")?.textContent).toBe("Sent");
    expect(button("Review & send", card())).toBeUndefined();
    expect(urls).toEqual([]);
  });

  it("shows a draft that could not be sent, with why, and the way to Outlook", async () => {
    responses["POST /api/mail/drafts/12/send"] = () =>
      json({ detail: { code: "exchange_access_denied", message: "You may not send as this mailbox." } }, 403);
    let read = 0;
    responses["GET /api/mail/drafts/12"] = () => {
      read += 1;
      return json(read === 1 ? LIVE : { ...LIVE, status: "failed", error: "You may not send as this mailbox.", change_key: undefined });
    };
    await render(<MailDraftCard card={CARD} />);
    await click(button("Review & send", card()));
    await click(button("Send", document.querySelector('[role="dialog"]')!));
    expect(card().querySelector(".mail-draft-card__status")?.textContent).toBe("Not sent");
    expect(card().querySelector(".mail-draft-card__error")?.textContent).toBe("You may not send as this mailbox.");
    expect(link("Open in Outlook", card())?.href).toBe(LIVE.owa_url);
  });

  it("shows a draft the dialog found gone from Drafts as discarded, with the server's reason", async () => {
    responses["GET /api/mail/drafts/12"] = () =>
      json({
        ...LIVE,
        status: "discarded",
        error: "The draft is no longer in Drafts: it was sent or deleted in Outlook.",
        change_key: undefined,
      });
    await render(<MailDraftCard card={CARD} />);
    await click(button("Review & send", card()));
    expect(card().querySelector(".mail-draft-card__status")?.textContent).toBe("Discarded");
    expect(card().querySelector(".mail-draft-card__error")?.textContent).toContain("no longer in Drafts");
    await click(button("Close", document.querySelector('[role="dialog"]')!));
    // The opener is gone: focus stays on the card, not lost to the page.
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 5));
    });
    expect(document.activeElement).toBe(card());
  });
});
