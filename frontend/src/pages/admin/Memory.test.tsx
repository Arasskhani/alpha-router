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
  jobs_by_status: {},
  project_learned_memories: 0,
  project_manual_memories: 0,
  project_embedding_backlog: 0,
  project_dead_letter_count: 0,
  project_extraction_cost_usd_30d: 0,
  project_jobs_by_status: {},
};

function answerWith(overrides: Record<string, unknown> = {}) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path.includes("/memory/settings")) return { ...SETTINGS, ...overrides };
    if (path.includes("/memory/stats")) return STATS;
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
