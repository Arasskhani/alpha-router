/**
 * @vitest-environment happy-dom
 *
 * Admin › Guardrails: the rules, a new rule, a pattern tried as it is written,
 * Test a text, settings, and a read-only administrator who only looks.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn(), authFetch: vi.fn(), formatApiError: (e: unknown) => String(e) }));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: async () => true }) }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { api } from "../../api";
import { messageMismatch, ruleProblem, type GuardrailsMeta } from "../../lib/guardrails";
import Guardrails from "./Guardrails";

const META: GuardrailsMeta = {
  channels: [
    { key: "chat", label: "Chat messages" },
    { key: "attachments", label: "Attached files" },
    { key: "web_fetch", label: "Web fetch addresses" },
  ],
  routable_channels: ["chat", "attachments", "extension", "gateway"],
  redactable_channels: ["chat", "attachments", "context", "extension", "gateway", "web_search"],
  trust_levels: [
    { key: "internal", label: "Internal" },
    { key: "trusted", label: "Trusted external" },
    { key: "public", label: "Public" },
  ],
  validators: [{ key: "luhn", label: "Card checksum (Luhn)" }],
  default_messages: { block: "Not sent.", redact: "Masked.", route: "Answered by {model}." },
  library: [],
  route_models: [{ id: 9, label: "Llama · Ollama", trust_level: "internal" }],
};
const OVERVIEW = {
  rules: { off: 0, monitor: 1, enforce: 1 },
  totals_7d: { block: 3, redact: 5, route: 0, monitor: 2, engine_error: 0 },
  top_by_action: { block: [{ name: "Keys", count: 3 }] },
  by_channel: [],
  top_rules: [],
  daily: [],
};
const RULE = {
  id: 1,
  name: "Cards to public models",
  description: "",
  mode: "enforce",
  position: 1,
  patterns: ["lib:bank_card"],
  pattern_names: ["Bank card"],
  missing_patterns: [],
  match_mode: "any",
  min_matches: 1,
  channels: ["chat", "attachments"],
  destinations: ["public"],
  action: "redact",
  route_model_id: null,
  route_model_label: null,
  user_message: "",
  access_type: "public",
  allow_count: 0,
  deny_count: 1,
  version: 2,
  hits_7d: 7,
  updated_at: null,
};
const PATTERNS = {
  custom: [],
  library: [{ ref: "lib:bank_card", name: "Bank card", description: "", kind: "regex", expression: "", validator: "luhn", redact_label: "CARD", case_sensitive: false, normalize: true, must_match: [], must_not_match: [], used_by: ["Cards to public models"], hits_7d: 7 }],
};

let host: HTMLDivElement;
let root: Root;
let calls: { url: string; init?: RequestInit }[];

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/meta")) return META;
    if (url.endsWith("/overview")) return OVERVIEW;
    if (url.endsWith("/rules") && !init?.method) return [RULE];
    if (url.endsWith("/patterns")) return PATTERNS;
    if (url.endsWith("/patterns/test")) return { ok: false, error: "Not a valid expression: missing ).", matches: [], problems: [] };
    if (url.endsWith("/test")) return { action: "block", message: "Not sent.", masked: null, rules: [] };
    if (url.endsWith("/settings") && !init?.method) return { fail_closed: true, restore_replies: true, event_retention_days: 180, alert_emails: [] };
    if (url.endsWith("/settings")) return JSON.parse(String(init!.body));
    return {};
  });
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
      <MemoryRouter>
        <Guardrails />
      </MemoryRouter>,
    );
  });
  await act(async () => undefined);
}

const button = (text: string | RegExp) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof text === "string" ? b.textContent?.trim() === text : text.test(b.textContent ?? ""),
  )!;
const tab = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => b.textContent === name)!;

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("the Guardrails page", () => {
  it("shows the rules in force and what they did this week", async () => {
    await render();
    expect(host.textContent).toContain("Enforcing 1 rule");
    expect(host.querySelector('[data-testid="guardrails-stat-block"]')!.textContent).toContain("Keys 3");
    const row = host.querySelector("tbody tr")!;
    expect(row.textContent).toContain("Cards to public models");
    expect(row.textContent).toContain("Everyone except 1");
    expect(row.textContent).toContain("Redact");
    expect(row.textContent).toContain("Public");
  });

  it("creates a rule with what the form holds, and says what is missing first", async () => {
    await render();
    await act(async () => button("+ New rule").click());
    const form = document.querySelector(".guardrails-form")!;
    await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(form.textContent).toContain("Name the rule.");
    await type(form.querySelector<HTMLInputElement>("input.input-block")!, "Cards");
    await act(async () => form.querySelector<HTMLInputElement>('input[value="lib:bank_card"]')!.click());
    await act(async () => form.querySelector<HTMLInputElement>('input[name="rule-action"][value="block"]')!.click());
    await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    const created = calls.find((c) => c.url.endsWith("/rules") && c.init?.method === "POST")!;
    expect(JSON.parse(String(created.init!.body))).toMatchObject({
      name: "Cards",
      mode: "monitor",
      patterns: ["lib:bank_card"],
      channels: ["chat", "attachments"],
      action: "block",
    });
  });

  it("says why a pattern cannot be used while it is written", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await render();
      await act(async () => tab("Patterns").click());
      await act(async () => button("+ New pattern").click());
      const form = document.querySelector(".guardrails-form")!;
      await type(form.querySelector<HTMLInputElement>(".guardrails-code")!, "(");
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      await act(async () => undefined);
      expect(form.textContent).toContain("Rejected: Not a valid expression: missing ).");
      expect(button("Save pattern").disabled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("tries a text and saves the settings", async () => {
    await render();
    await act(async () => button("Test a text").click());
    await type(document.querySelector<HTMLTextAreaElement>(".guardrails-form textarea")!, "sk-proj-123");
    await act(async () => button("Test").click());
    expect(document.querySelector('[data-testid="guardrails-test-result"]')!.textContent).toContain("Block");
    await act(async () => button("Close").click());
    await act(async () => tab("Settings").click());
    await act(async () => undefined);
    await act(async () => document.querySelector<HTMLInputElement>('input[name="fail"]:not(:checked)')!.click());
    await act(async () => button("Save settings").click());
    const put = calls.find((c) => c.url.endsWith("/settings") && c.init?.method === "PUT")!;
    expect(JSON.parse(String(put.init!.body))).toMatchObject({ fail_closed: false });
  });

  it("offers a read-only administrator nothing to change", async () => {
    readOnly.value = true;
    await render();
    expect(button("+ New rule")).toBeUndefined();
    expect(button("Test a text")).toBeUndefined();
  });
});

describe("a rule's own checks", () => {
  const base = { name: "R", description: "", mode: "enforce" as const, patterns: ["lib:x"], match_mode: "any" as const, min_matches: 1, channels: ["chat" as const], destinations: [], action: "redact" as const, route_model_id: null, user_message: "" };
  it("route needs a model and chat-like channels; an address cannot be masked", () => {
    expect(ruleProblem(base, META)).toBe("");
    expect(ruleProblem({ ...base, action: "route" }, META)).toBe("Choose the model to route to.");
    expect(ruleProblem({ ...base, action: "route", route_model_id: 9, channels: ["web_fetch"] }, META)).toContain("routed");
    expect(ruleProblem({ ...base, channels: ["web_fetch"] }, META)).toContain("cannot be masked");
    expect(ruleProblem({ ...base, patterns: [] }, META)).toBe("Choose at least one pattern to detect.");
  });
});

describe("a rule's message", () => {
  it("is flagged when it speaks of another action than the rule takes", () => {
    expect(messageMismatch("redact", "block by admin")).toContain("the rule masks");
    expect(messageMismatch("route", "این پیام مسدود شد")).toContain("the rule routes");
    expect(messageMismatch("block", "Card numbers were masked.")).toContain("the rule blocks");
    expect(messageMismatch("block", "Card numbers may not be sent; blocked.")).toBe("");
    expect(messageMismatch("redact", "Card numbers were masked.")).toBe("");
    expect(messageMismatch("redact", "")).toBe("");
  });
});
