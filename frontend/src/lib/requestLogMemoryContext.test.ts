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
});
