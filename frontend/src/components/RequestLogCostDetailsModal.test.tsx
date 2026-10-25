/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import RequestLogCostDetailsModal from "./RequestLogCostDetailsModal";
import type { CostDetails, RequestLogSummary } from "../lib/requestLogCostDetails";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const LOG = {
  id: 42,
  request_time: "2026-09-30T08:00:00",
  username: "sara",
  model_id: "gpt-4o-mini",
  prompt_language: "en",
  prompt_tokens: 10,
  completion_tokens: 5,
  total_cost_usd: 0.001,
} as RequestLogSummary;

function details(memoryContext: unknown): CostDetails {
  return {
    operation: null,
    events: [],
    legacy: false,
    request: {
      id: 42,
      success: true,
      error_code: null,
      error_message: null,
      http_status: null,
      response_time_ms: 10,
      source: "alpha_router_chat",
      client_app: null,
      model_id: "gpt-4o-mini",
      project_id: null,
      ...(memoryContext === undefined ? {} : { memory_context: memoryContext }),
    },
  } as CostDetails;
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function render(costDetails: CostDetails | null, { loading = false, error = "" } = {}) {
  act(() => {
    root.render(
      <MemoryRouter>
        <RequestLogCostDetailsModal
          open
          log={LOG}
          details={costDetails}
          loading={loading}
          error={error}
          onClose={() => undefined}
        />
      </MemoryRouter>,
    );
  });
}

function section(): Element | null {
  return [...document.querySelectorAll("h4")].find((h) => h.textContent === "Memory and context")?.parentElement ?? null;
}

describe("the Memory and context section of a request's details", () => {
  it("says what a chat turn was given beside its messages, the earlier chats by id", () => {
    render(details({ memories: 2, recalled_chats: ["chat-a"], context_fit: { dropped: 4, summarized: 0 } }));
    const shown = section();
    expect(shown?.textContent).toContain("2 personal");
    expect(shown?.textContent).toContain("Earlier chats read (1)");
    expect(shown?.querySelector(".api-log-cost-details__mono")?.textContent).toBe("chat-a");
    expect(shown?.textContent).toContain("4 older messages");
  });

  it("lists the mail tools the turn called, each with its arguments and outcome", () => {
    render(
      details({
        mail_tools: [
          { tool: "mail_search", args: { folder: "inbox", query: "budget" }, result: "ok" },
          { tool: "mail_read", args: { refs: ["m7Q2xY"] }, result: "exchange_auth" },
        ],
      }),
    );
    const rows = [...(section()?.querySelectorAll("dl > div") ?? [])].map((row) => [
      row.querySelector("dt")?.textContent,
      row.querySelector("dd")?.textContent,
      row.querySelector("dd")?.className,
    ]);
    expect(rows).toEqual([
      ["Mail tool 1", "mail_search (folder: inbox, query: budget) → OK", "api-log-cost-details__mono"],
      ["Mail tool 2", "mail_read (refs: m7Q2xY) → Exchange: auth", "api-log-cost-details__mono"],
    ]);
  });

  it("is not there for a request that was given nothing, nor for the person's own view, nor while loading", () => {
    render(details(null));
    expect(section()).toBeNull();
    render(details(undefined));
    expect(section()).toBeNull();
    render(details({ memories: 2 }), { loading: true });
    expect(section()).toBeNull();
    render(details({ memories: 2 }), { error: "Could not load" });
    expect(section()).toBeNull();
  });
});
