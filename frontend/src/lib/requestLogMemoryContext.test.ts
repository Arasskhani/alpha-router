import { describe, expect, it } from "vitest";
import { memoryContextRows } from "./requestLogCostDetails";

const at = (iso: string) => `at ${iso}`;

describe("memoryContextRows", () => {
  it("says nothing for a request that was given nothing", () => {
    expect(memoryContextRows(null, at)).toEqual([]);
    expect(memoryContextRows({}, at)).toEqual([]);
  });

  it("names the memories, the earlier chats by id, what was left out and the summary used", () => {
    const rows = memoryContextRows(
      {
        memories: 3,
        project_memories: 2,
        recalled_chats: ["chat-a", "chat-b"],
        context_fit: {
          dropped: 40,
          summarized: 38,
          window: 16000,
          tokens_before: 21000,
          tokens_after: 11800,
          summary: { up_to: 40, version: "2026-09-30T08:00:00", tokens: 600 },
        },
      },
      at,
    );
    expect(rows.map((row) => row.label)).toEqual([
      "Memories",
      "Earlier chats read (2)",
      "Left out to fit",
      "Summary used",
    ]);
    expect(rows[0].value).toBe("3 personal · 2 project");
    expect(rows[1].value).toBe("chat-a, chat-b");
    expect(rows[1].mono).toBe(true);
    expect(rows[2].value).toContain("40 older messages (38 read as the summary)");
    expect(rows[2].value).toContain("tokens");
    expect(rows[3].value).toContain("up to message #40");
    expect(rows[3].value).toContain("last updated at 2026-09-30T08:00:00");
  });

  it("says a summary stood in when it knows nothing more of it, and a window without its token counts", () => {
    const rows = memoryContextRows(
      { context_fit: { dropped: 3, summarized: 3, window: 8000, summary: { up_to: null, version: null } } },
      at,
    );
    expect(rows).toEqual([
      { label: "Left out to fit", value: "3 older messages (3 read as the summary) · window 8,000 tokens" },
      { label: "Summary used", value: "Yes" },
    ]);
  });

  it("leaves the summary out when none stood in", () => {
    const rows = memoryContextRows({ context_fit: { dropped: 1, summarized: 0 } }, at);
    expect(rows).toEqual([{ label: "Left out to fit", value: "1 older message" }]);
  });

  it("lists each mail tool call: the tool, its logged arguments and its outcome", () => {
    const rows = memoryContextRows(
      {
        memories: 1,
        mail_tools: [
          { tool: "mail_search", args: { folder: "inbox", query: "budget from:<address>", limit: 10, from_given: true }, result: "ok" },
          { tool: "mail_read", args: { refs: ["m7Q2xY", "k3Pz9A"] }, result: "exchange_auth" },
          { tool: "mail_create_draft", args: { kind: "reply", ref: "m7Q2xY", to_count: 2, cc_count: 0 }, result: "timeout" },
          { tool: "calendar_find_free_time", args: {}, result: "throttled_somehow" },
          { tool: "people_find", result: null },
        ],
      },
      at,
    );
    expect(rows).toEqual([
      { label: "Memories", value: "1 personal" },
      {
        label: "Mail tool 1",
        value: "mail_search (folder: inbox, query: budget from:<address>, limit: 10, from_given: true) → OK",
        mono: true,
      },
      { label: "Mail tool 2", value: "mail_read (refs: m7Q2xY k3Pz9A) → Exchange: auth", mono: true },
      { label: "Mail tool 3", value: "mail_create_draft (kind: reply, ref: m7Q2xY, to_count: 2, cc_count: 0) → Timed out", mono: true },
      { label: "Mail tool 4", value: "calendar_find_free_time → throttled somehow", mono: true },
      { label: "Mail tool 5", value: "people_find → —", mono: true },
    ]);
  });

  it("leaves out malformed mail tool entries and cuts long arguments short", () => {
    const rows = memoryContextRows(
      { mail_tools: [null, "mail_search", { args: {} }, { tool: "mail_search", args: { query: "x".repeat(200) }, result: "ok" }] } as never,
      at,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("Mail tool 1");
    expect(rows[0].value).toContain(`query: ${"x".repeat(79)}…`);
    expect(rows[0].value.length).toBeLessThan(120);
  });
});
