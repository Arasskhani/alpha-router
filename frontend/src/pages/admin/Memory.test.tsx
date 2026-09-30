/**
 * @vitest-environment happy-dom
 *
 * The page can be switched on and still be doing nothing. feature_enabled
 * defaults to true, memory_extraction_model_id defaults to "", and the only
 * thing that said so was a sentence in muted-text above the fold. Users get a
 * real banner about it in their own Memory panel; the admin — the one person
 * who can fix it — got the quietest version of the message.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn(), formatApiError: (e: unknown) => String(e) }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));
vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), prompt: vi.fn() }),
}));

import { api } from "../../api";
import MemoryAdmin from "./Memory";

const SETTINGS = {
  feature_enabled: true,
  extraction_model_id: null as number | null,
  embedding_model: "",
  embedding_dimensions: null,
  extract_debounce_seconds: 30,
  extract_max_wait_seconds: 600,
  extract_min_new_messages: 2,
  extract_max_tokens: 2000,
  extract_monthly_budget_usd: 0,
  max_per_user: 200,
  inject_max_items: 12,
  inject_max_chars: 2500,
  core_items: 6,
  semantic_top_k: 8,
  lexical_top_k: 6,
  min_similarity: 0.25,
  retrieval_timeout_ms: 600,
  allowed_sensitive_categories: ["health", "financial"],
  stale_archive_days: 540,
  soft_delete_purge_days: 30,
  suppression_days: 180,
  history_completion_enabled: true,
  relearn_enabled: false,
  context_fit_enabled: true,
  context_share_percent: 75,
  context_default_tokens: 0,
  summary_enabled: true,
  summary_model_id: null as number | null,
  summary_keep_recent: 20,
  summary_monthly_budget_usd: 0,
  recall_enabled: true,
  recall_max_items: 4,
  recall_max_chars: 3000,
  recall_min_similarity: 0.35,
  plan_memory_enabled: true,
  plan_ttl_days: 90,
  project_feature_enabled: true,
  project_max_per_project: 500,
  project_inject_max_items: 60,
  project_inject_max_chars: 8000,
  project_manual_items: 30,
  project_extract_debounce_seconds: 45,
  project_extract_max_wait_seconds: 900,
  project_extract_min_new_messages: 2,
  project_semantic_top_k: 12,
  project_lexical_top_k: 8,
  project_min_similarity: 0.25,
};

const STATS = {
  total_memories: 0,
  memories_last_7d: 0,
  embedding_backlog: 0,
  dead_letter_count: 0,
  oldest_pending_job_age_seconds: null,
  extraction_cost_usd_30d: 0,
  extraction_cost_usd_mtd: 0,
  jobs_by_status: {},
  project_learned_memories: 0,
  project_manual_memories: 0,
  project_embedding_backlog: 0,
  project_dead_letter_count: 0,
  project_extraction_cost_usd_30d: 0,
  project_jobs_by_status: {},
};

function answerWith(overrides: Record<string, unknown> = {}, statOverrides: Record<string, unknown> = {}) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path.includes("/memory/settings")) return { ...SETTINGS, ...overrides };
    if (path.includes("/memory/stats")) return { ...STATS, ...statOverrides };
    if (path.includes("/admin/models")) {
      return [{ id: 7, external_id: "gpt-x", display_name: "GPT X", provider: "openai", enabled: true, kinds: ["text"] }];
    }
    throw new Error(`unexpected ${path}`);
  });
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
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
        <MemoryAdmin />
      </MemoryRouter>,
    );
  });
}

function warning() {
  return host.querySelector(".alert-warning");
}

describe("the admin Memory page", () => {
  it("says plainly that nothing is being learned when no model is picked", async () => {
    answerWith();
    await render();
    expect(warning()?.textContent).toContain("Nothing is being learned");
    expect(warning()?.textContent).toContain("Extraction model");
  });

  it("drops the warning once a model is selected", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    expect(warning()).toBeNull();
  });

  it("stays quiet when the feature itself is switched off", async () => {
    // Off with no model is a coherent state, not a misconfiguration.
    answerWith({ feature_enabled: false });
    await render();
    expect(warning()).toBeNull();
  });
});

describe("the extraction spend cap", () => {
  it("offers the cap before anything else on the page", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const sections = [...host.querySelectorAll("section")];
    expect(sections[0]?.getAttribute("aria-label")).toBe("Cost control");
    expect(sections[0]?.textContent).toContain("Monthly extraction budget");
  });

  it("explains that zero is not a limit", async () => {
    answerWith({ extraction_model_id: 7, extract_monthly_budget_usd: 0 });
    await render();
    expect(host.textContent).toContain("0 means no limit");
    expect(host.querySelector(".alert-warning")).toBeNull();
  });

  it("shows what has been spent against the cap", async () => {
    answerWith({ extraction_model_id: 7, extract_monthly_budget_usd: 20 }, { extraction_cost_usd_mtd: 4.5 });
    await render();
    expect(host.textContent).toContain("$4.50 of $20.00 used this month");
    expect(host.querySelector(".alert-warning")).toBeNull();
  });

  it("says extraction has stopped once the cap is reached", async () => {
    answerWith({ extraction_model_id: 7, extract_monthly_budget_usd: 20 }, { extraction_cost_usd_mtd: 21 });
    await render();
    expect(host.querySelector(".alert-warning")?.textContent).toContain("Extraction is paused");
  });
});

describe("the links out of Cost control", () => {
  it("offers both reports, with the report preselected in the link", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const links = [...host.querySelectorAll(".memory-admin__budget-links a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/admin/reports?report=memory_cost_by_user",
      "/admin/reports?report=memory_cost_summary",
    ]);
  });

  it("keeps them beside the figure that raises the question", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const costControl = host.querySelector('section[aria-label="Cost control"]');
    expect(costControl?.querySelector(".memory-admin__budget-links")).not.toBeNull();
  });
});

describe("the chat history switch", () => {
  function toggle() {
    return host.querySelector<HTMLButtonElement>('button[aria-label="Complete history on the server"]');
  }

  it("shows the server's setting and sends the change on Save", async () => {
    answerWith({ extraction_model_id: 7, history_completion_enabled: true });
    await render();
    expect(toggle()?.getAttribute("aria-pressed")).toBe("true");
    await act(async () => toggle()?.click());
    expect(toggle()?.getAttribute("aria-pressed")).toBe("false");
    const form = host.querySelector<HTMLFormElement>("#memory-settings-form");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const patchCall = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    expect(JSON.parse(String((patchCall?.[1] as RequestInit).body)).history_completion_enabled).toBe(false);
  });
});

describe("the extractor's answer length", () => {
  it("shows the server's figure and sends a new one on Save", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const input = host.querySelector<HTMLInputElement>("#memory-extract-max-tokens");
    expect(input?.value).toBe("2000");
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setValue?.call(input, "3000");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = host.querySelector<HTMLFormElement>("#memory-settings-form");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const patchCall = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    expect(JSON.parse(String((patchCall?.[1] as RequestInit).body)).extract_max_tokens).toBe(3000);
  });
});

describe("the failed jobs", () => {
  const USER_FAILED = {
    scope: "user",
    total: 3,
    reasons: [
      { reason: "Memory extraction model is unavailable", count: 2 },
      { reason: "RateLimitError: slow down", count: 1 },
    ],
    jobs: [],
  };

  function answerWithFailures() {
    vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.includes("/memory/failed-jobs/retry")) return { requeued: 2, merged: 1, covered: 0 };
      if (path.includes("/memory/failed-jobs?scope=user")) return USER_FAILED;
      if (path.includes("/memory/failed-jobs?scope=project")) return { scope: "project", total: 0, reasons: [], jobs: [] };
      if (path.includes("/memory/settings")) return { ...SETTINGS, extraction_model_id: 7 };
      if (path.includes("/memory/stats")) return { ...STATS, dead_letter_count: 3 };
      if (path.includes("/admin/models")) return [];
      throw new Error(`unexpected ${path} ${init?.method ?? "GET"}`);
    });
  }

  function section() {
    return host.querySelector('section[aria-label="Failed jobs"]');
  }

  it("says why they failed and runs a scope's jobs again", async () => {
    answerWithFailures();
    await render();
    await act(async () => undefined);
    const text = section()?.textContent ?? "";
    expect(text).toContain("3 failed");
    expect(text).toContain("2 Memory extraction model is unavailable");
    expect(text).toContain("None");
    const [personal, project] = Array.from(section()?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    expect(project.disabled).toBe(true);
    await act(async () => personal.click());
    const retry = vi.mocked(api).mock.calls.find(([path]) => String(path).includes("/failed-jobs/retry"));
    expect(JSON.parse(String((retry?.[1] as RequestInit).body))).toEqual({ scope: "user" });
    expect(host.querySelector(".alert-success")?.textContent).toContain("Queued 2 again");
  });

  it("keeps the settings being edited when the jobs are run again", async () => {
    answerWithFailures();
    await render();
    await act(async () => undefined);
    const keep = host.querySelector<HTMLInputElement>("#memory-summary-keep");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(keep, "31");
      keep?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const [personal] = Array.from(section()?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    await act(async () => personal.click());
    expect(host.querySelector<HTMLInputElement>("#memory-summary-keep")?.value).toBe("31");
    expect(vi.mocked(api).mock.calls.filter(([path]) => String(path).includes("/memory/settings"))).toHaveLength(1);
  });

  it("still opens the page when the list cannot be read, and says it could not", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    await act(async () => undefined);
    expect(section()?.textContent).toContain("Failed jobs");
    expect(section()?.textContent).toContain("Could not load");
    expect(host.querySelector(".alert-error")).toBeNull();
  });
});

describe("relearning recent chats", () => {
  const ESTIMATE = {
    enabled: true,
    model_configured: true,
    days: 30,
    chats: { user: 2, project: 1 },
    messages: 40,
    characters: 52000,
    parts: 5,
    estimated_cost_usd: 0.0123,
    spent_this_month_usd: 1.5,
    monthly_cap_usd: 10,
  };

  function answerWithEstimate(estimate: Record<string, unknown>) {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.includes("/memory/relearn/estimate")) return estimate;
      if (path.endsWith("/memory/relearn")) return { queued: 3, merged: 0 };
      if (path.includes("/memory/failed-jobs")) return { scope: "user", total: 0, reasons: [], jobs: [] };
      if (path.includes("/memory/settings")) return { ...SETTINGS, extraction_model_id: 7, relearn_enabled: true };
      if (path.includes("/memory/stats")) return STATS;
      if (path.includes("/admin/models")) return [];
      throw new Error(`unexpected ${path}`);
    });
  }

  function section() {
    return host.querySelector('section[aria-label="Relearn recent chats"]');
  }

  function button(label: string) {
    return Array.from(section()?.querySelectorAll<HTMLButtonElement>("button") ?? []).find((b) => b.textContent === label);
  }

  it("estimates first, then queues the chats after a confirmation", async () => {
    answerWithEstimate(ESTIMATE);
    await render();
    expect(button("Relearn")?.disabled).toBe(true);
    await act(async () => button("Estimate")?.click());
    expect(section()?.textContent).toContain("3 chats (2 personal, 1 project), 40 messages in 5 parts: about $0.0123.");
    expect(section()?.textContent).toContain("This month: $1.50 of $10.00");
    expect(button("Relearn")?.disabled).toBe(false);
    await act(async () => button("Relearn")?.click());
    const start = vi.mocked(api).mock.calls.find(([path]) => String(path).endsWith("/memory/relearn"));
    expect(JSON.parse(String((start?.[1] as RequestInit).body))).toEqual({ days: 30 });
    expect(host.querySelector(".alert-success")?.textContent).toContain("Queued 3 chats");
  });

  it("cannot start while the switch is off on the server, and says so", async () => {
    answerWithEstimate({ ...ESTIMATE, enabled: false });
    await render();
    await act(async () => button("Estimate")?.click());
    expect(button("Relearn")?.disabled).toBe(true);
    expect(section()?.textContent).toContain("Relearning is off: turn on Allow relearning and save first.");
  });

  it("waits for the switch to be saved before it estimates", async () => {
    answerWithEstimate(ESTIMATE);
    await render();
    const toggle = section()?.querySelector<HTMLButtonElement>('button[aria-label="Allow relearning"]');
    await act(async () => toggle?.click());
    expect(button("Estimate")?.disabled).toBe(true);
    expect(section()?.textContent).toContain("Save your changes first");
    await act(async () => toggle?.click());
    expect(button("Estimate")?.disabled).toBe(false);
  });
});

describe("long chats", () => {
  function section() {
    return host.querySelector('section[aria-label="Long chats"]');
  }

  it("says a summary needs a model, and sends the section's settings on Save", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    expect(section()?.textContent).toContain("Needs a summary model.");
    const toggle = section()?.querySelector<HTMLButtonElement>('button[aria-label="Fit each turn into the model\'s window"]');
    expect(toggle?.getAttribute("aria-pressed")).toBe("true");
    await act(async () => toggle?.click());
    const keep = host.querySelector<HTMLInputElement>("#memory-summary-keep");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(keep, "30");
      keep?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // With fitting off, its own numbers cannot be changed.
    expect(host.querySelector<HTMLInputElement>("#memory-context-share")?.disabled).toBe(true);
    const form = host.querySelector<HTMLFormElement>("#memory-settings-form");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const patchCall = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    const body = JSON.parse(String((patchCall?.[1] as RequestInit).body));
    expect(body.context_fit_enabled).toBe(false);
    expect(body.summary_keep_recent).toBe(30);
  });

  it("describes what a summary does once a model is chosen", async () => {
    answerWith({ extraction_model_id: 7, summary_model_id: 7 });
    await render();
    expect(section()?.textContent).toContain("Keeps a summary of each long chat's older messages");
  });
});

describe("earlier chats", () => {
  function section() {
    return host.querySelector('section[aria-label="Earlier chats"]');
  }

  function answerWithRecall(overrides: Record<string, unknown>, estimate: Record<string, unknown>) {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.includes("/memory/recall/status")) {
        return { embedding_model_configured: true, enabled: true, indexed_chats: 12, chunks: 340, pending: 2, running: 0, failed: 1 };
      }
      if (path.includes("/memory/recall/backfill/estimate")) return estimate;
      if (path.endsWith("/memory/recall/backfill")) return { queued: 30 };
      if (path.includes("/memory/failed-jobs")) return { scope: "user", total: 0, reasons: [], jobs: [] };
      if (path.includes("/memory/settings")) return { ...SETTINGS, extraction_model_id: 7, ...overrides };
      if (path.includes("/memory/stats")) return STATS;
      if (path.includes("/admin/models")) return [];
      throw new Error(`unexpected ${path}`);
    });
  }

  function button(label: string) {
    return Array.from(section()?.querySelectorAll<HTMLButtonElement>("button") ?? []).find((b) => b.textContent === label);
  }

  it("says when how far the index has got could not be read", async () => {
    answerWith({ extraction_model_id: 7, embedding_model: "openai:text-embedding-3-small", embedding_dimensions: 1536 });
    await render();
    await act(async () => undefined);
    expect(section()?.textContent).toContain("Could not load how far the index has got.");
  });

  it("is locked, and says why, without an embedding model", async () => {
    answerWithRecall({ embedding_model: "" }, {});
    await render();
    expect(section()?.textContent).toContain("Recall needs an embedding model");
    const toggle = section()?.querySelector<HTMLButtonElement>('button[aria-label="Recall earlier chats"]');
    expect(toggle?.disabled).toBe(true);
    expect(toggle?.getAttribute("aria-pressed")).toBe("false");
  });

  it("shows the index's progress, estimates the backfill and queues it", async () => {
    answerWithRecall(
      { embedding_model: "openai:text-embedding-3-small", embedding_dimensions: 1536 },
      { chats: 30, messages: 900, characters: 400000, estimated_cost_usd: 0.0021, enabled: true },
    );
    await render();
    await act(async () => undefined);
    expect(section()?.textContent).toContain("12 chats indexed (340 exchanges); 2 queued, 1 failed.");
    expect(button("Index")?.disabled).toBe(true);
    await act(async () => button("Estimate")?.click());
    expect(section()?.textContent).toContain("30 chats, 900 messages not indexed yet: about $0.0021.");
    await act(async () => button("Index")?.click());
    expect(vi.mocked(api).mock.calls.some(([path, init]) => String(path).endsWith("/memory/recall/backfill") && (init as RequestInit)?.method === "POST")).toBe(true);
    expect(host.querySelector(".alert-success")?.textContent).toContain("Queued 30 chats to be indexed.");
  });

  it("says why it cannot index while recall is off on the server", async () => {
    answerWithRecall(
      { embedding_model: "openai:text-embedding-3-small", embedding_dimensions: 1536 },
      { chats: 30, messages: 900, characters: 400000, estimated_cost_usd: 0.0021, enabled: false },
    );
    await render();
    await act(async () => button("Estimate")?.click());
    expect(section()?.textContent).toContain("Recall is off, or no embedding model is saved");
    expect(button("Index")?.disabled).toBe(true);
  });
});

describe("plans and routines", () => {
  it("has a switch, and a time that cannot be changed while it is off", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const toggle = host.querySelector<HTMLButtonElement>('button[aria-label="Remember ongoing plans and routines"]');
    expect(toggle?.getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector<HTMLInputElement>("#memory-plan-days")?.value).toBe("90");
    await act(async () => toggle?.click());
    expect(host.querySelector<HTMLInputElement>("#memory-plan-days")?.disabled).toBe(true);
    const form = host.querySelector<HTMLFormElement>("#memory-settings-form");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const patchCall = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    expect(JSON.parse(String((patchCall?.[1] as RequestInit).body)).plan_memory_enabled).toBe(false);
  });
});

describe("the setup steps", () => {
  function section() {
    return host.querySelector('section[aria-label="Setup"]');
  }

  it("say what is missing without each model", async () => {
    answerWith();
    await render();
    const steps = [...(section()?.querySelectorAll("li") ?? [])];
    expect(steps.map((li) => li.getAttribute("data-done"))).toEqual(["false", "false"]);
    expect(section()?.textContent).toContain("Not chosen: nothing is learned.");
    expect(section()?.textContent).toContain("earlier chats are not recalled");
  });

  it("say which models are chosen", async () => {
    answerWith({ extraction_model_id: 7, embedding_model: "openai:text-embedding-3-small", embedding_dimensions: 1536 });
    await render();
    const done = [...(section()?.querySelectorAll("li") ?? [])];
    expect(done.map((li) => li.getAttribute("data-done"))).toEqual(["true", "true"]);
    expect(section()?.textContent).toContain("Chosen: GPT X.");
    expect(section()?.textContent).toContain("After changing it, Rebuild index.");
  });

  it("name each button by the model it is for", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const names = [...(section()?.querySelectorAll("button") ?? [])].map((b) => b.getAttribute("aria-label"));
    expect(names).toEqual(["Change the extraction model", "Choose the embedding model"]);
  });
});

describe("rows with several controls", () => {
  it("are marked to go under their title on a phone", async () => {
    answerWith({ extraction_model_id: 7 });
    await render();
    const rows = [...host.querySelectorAll(".settings-row-block--actions")].map(
      (row) => row.querySelector(".settings-row__title")?.textContent,
    );
    expect(rows).toEqual(["Days to read again", "Index earlier chats"]);
  });
});

