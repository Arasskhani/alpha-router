/**
 * @vitest-environment happy-dom
 *
 * Draft cards from the turn's stream (`alpha_router.mail_drafts`), joined by
 * id across frames, and what the tab remembers about a finished draft.
 */
import { beforeEach, describe, expect, it } from "vitest";

import type { MailDraftCard } from "./exchangeMail";
import {
  knownDraftOutcome,
  mergeMailDraftCards,
  readStreamMailDrafts,
  recipientNames,
  rememberDraftOutcome,
} from "./mailDraftCards";

const card = (id: number, subject = `Draft ${id}`): MailDraftCard => ({
  id,
  mailbox: "s.karimi@corp.example",
  kind: "reply",
  subject,
  to: [{ name: "Ali Rezaei", email: "a.rezaei@corp.example" }],
  cc: [],
  preview: "Hello Ali,",
});

describe("draft cards from the stream", () => {
  it("are read from a frame's alpha_router block, malformed ones dropped", () => {
    const frame = {
      mail_drafts: [
        { id: 12, mailbox: "s.karimi@corp.example", kind: "reply_all", subject: "Re: Budget", to: [{ name: "Ali", email: "a@corp.example" }, { name: "no address" }], cc: [], preview: "Thanks" },
        { id: "13", subject: "no id" },
        { id: 14, kind: "teleport", subject: "Odd kind" },
      ],
    };
    expect(readStreamMailDrafts(undefined, frame)).toEqual([
      { id: 12, mailbox: "s.karimi@corp.example", kind: "reply_all", subject: "Re: Budget", to: [{ name: "Ali", email: "a@corp.example" }], cc: [], preview: "Thanks" },
      { id: 14, mailbox: "", kind: "new", subject: "Odd kind", to: [], cc: [], preview: "" },
    ]);
  });

  it("keep what earlier frames brought: a frame without cards changes nothing", () => {
    const first = readStreamMailDrafts(undefined, { mail_drafts: [card(1)] });
    expect(readStreamMailDrafts(first, { request_log_id: 9 })).toBe(first);
    expect(readStreamMailDrafts(first, undefined)).toBe(first);
    expect(readStreamMailDrafts(first, { mail_drafts: "x" })).toBe(first);
    expect(readStreamMailDrafts(undefined, {})).toBeUndefined();
  });

  it("join a later round's cards to the earlier ones by id, a newer copy replacing the older in place", () => {
    const rounds = readStreamMailDrafts(readStreamMailDrafts(undefined, { mail_drafts: [card(1), card(2)] }), {
      mail_drafts: [card(2, "Re: Budget (v2)"), card(3)],
    });
    expect(rounds?.map((c) => [c.id, c.subject])).toEqual([
      [1, "Draft 1"],
      [2, "Re: Budget (v2)"],
      [3, "Draft 3"],
    ]);
    expect(mergeMailDraftCards(undefined, undefined)).toBeUndefined();
    expect(mergeMailDraftCards([card(1)], [])).toEqual([card(1)]);
  });
});

describe("what a tab remembers about a draft", () => {
  beforeEach(() => sessionStorage.clear());

  it("keeps finished drafts only, with their error", () => {
    rememberDraftOutcome({ id: 5, status: "draft", error: null });
    expect(knownDraftOutcome(5)).toBeNull();
    rememberDraftOutcome({ id: 5, status: "sent", error: null });
    rememberDraftOutcome({ id: 6, status: "failed", error: "You may not send as this mailbox." });
    expect(knownDraftOutcome(5)).toEqual({ status: "sent", error: null });
    expect(knownDraftOutcome(6)).toEqual({ status: "failed", error: "You may not send as this mailbox." });
    expect(knownDraftOutcome(7)).toBeNull();
  });

  it("keeps the latest hundred, and shrugs at storage it cannot read", () => {
    for (let id = 1; id <= 105; id += 1) rememberDraftOutcome({ id, status: "discarded", error: null });
    expect(knownDraftOutcome(1)).toBeNull();
    expect(knownDraftOutcome(5)).toBeNull();
    expect(knownDraftOutcome(6)).toEqual({ status: "discarded", error: null });
    expect(knownDraftOutcome(105)).toEqual({ status: "discarded", error: null });

    sessionStorage.setItem("alpha_router_mail_draft_outcomes", "{not json");
    expect(knownDraftOutcome(105)).toBeNull();
    sessionStorage.setItem("alpha_router_mail_draft_outcomes", JSON.stringify([{ id: 8, status: "teleported" }]));
    expect(knownDraftOutcome(8)).toBeNull();
  });
});

describe("recipientNames", () => {
  it("uses names where known, addresses otherwise", () => {
    expect(recipientNames([{ name: "Ali Rezaei", email: "a@x.example" }, { name: " ", email: "b@x.example" }])).toBe(
      "Ali Rezaei, b@x.example",
    );
  });
});
