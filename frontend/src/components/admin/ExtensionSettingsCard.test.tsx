/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../api", () => ({ api: vi.fn(), formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
vi.mock("../../lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));

import { api } from "../../api";
import { copyTextToClipboard } from "../../lib/clipboard";
import ExtensionSettingsCard, { numberField, siteLines } from "./ExtensionSettingsCard";

const SETTINGS = {
  site_access: "per_site",
  allowed_sites: ["wiki.example.com"],
  blocked_sites: ["*.bank.example"],
  read_only_sites: [],
  protected_sites: [],
  internal_sites: [],
  internal_models: [],
  screenshot_models: [],
  page_content_models: ["model::2"],
  agent_models: [],
  agent_max_steps: 25,
  agent_auto_mode: false,
  agent_review_model: null,
  agent_recommended_model: null,
  full_control: false,
  enabled: true,
  relaxed_approvals: [],
  require_newest_package: false,
  min_browser_version: 116,
  internal_connections: [],
  external_screenshots: true,
  plan_mode: true,
  agent_default_mode: "plan",
  agent_max_minutes: 20,
  agent_max_tabs: 10,
  agent_runs_per_day: null,
  screenshot_max_side: 1280,
  screenshots_kept: 3,
  screenshot_after_action: true,
  save_runs: true,
  private_runs: true,
};
const CONNECTIONS = [
  { id: 1, name: "OpenAI", provider: "openai", host: "api.openai.com", active: true, looks_internal: false, state: "ok" },
  { id: 2, name: "Ollama box", provider: "custom", host: "10.0.0.5", active: true, looks_internal: true, state: "ok" },
];
const DISTRIBUTION = {
  available: true,
  reason: null,
  version: "1.0.0.3",
  extension_id: "abcdefghijklmnopabcdefghijklmnop",
  update_url: "https://ai.example.com/extension/update.xml",
  gpo_value: "abcdefghijklmnopabcdefghijklmnop;https://ai.example.com/extension/update.xml",
  key_status: "ok",
  key_message: null,
};
// As the server lists them: the enabled chat models, and any other model the settings name.
const MODELS = [
  { ref: "model::1", label: "GPT A", provider: "openai", state: "ok" },
  { ref: "model::2", label: "GPT B", provider: "openai", state: "ok" },
];

let probed: string[] = [];
let host: HTMLDivElement;
let root: Root;
let lastPut: Record<string, unknown> | null;

function serve(
  overrides: {
    settings?: object;
    models?: object[];
    distribution?: object;
    put?: (body: Record<string, unknown>) => unknown;
    probe?: (ref: string) => unknown;
    probes?: Record<string, unknown>;
  } = {},
) {
  const models = overrides.models ?? MODELS;
  vi.mocked(api).mockImplementation((async (path: string, init?: RequestInit) => {
    if (path.startsWith("/api/admin/extension/probe/")) {
      probed.push(decodeURIComponent(path.slice("/api/admin/extension/probe/".length)));
      if (overrides.probe) return overrides.probe(probed.at(-1)!);
      return { model_ref: probed.at(-1), ran_at: "2026-09-27T10:00:00Z", vision: true, tool_calling: true, hits: 3, trials: 3, passed: true, detail: "Clicked inside the button in 3 of 3 trials." };
    }
    if (path !== "/api/admin/extension/settings") throw new Error(`unexpected request to ${path}`);
    if (init?.method === "PUT") {
      lastPut = JSON.parse(String(init.body));
      if (overrides.put) return overrides.put(lastPut!);
      return { settings: { ...SETTINGS, ...lastPut }, models, connections: CONNECTIONS, distribution: DISTRIBUTION };
    }
    return {
      settings: { ...SETTINGS, ...overrides.settings },
      models,
      connections: CONNECTIONS,
      distribution: { ...DISTRIBUTION, ...overrides.distribution },
      probes: overrides.probes ?? {},
    };
  }) as never);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  readOnly.value = false;
  lastPut = null;
  probed = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render() {
  await act(async () =>
    root.render(
      <MemoryRouter>
        <ExtensionSettingsCard />
      </MemoryRouter>,
    ),
  );
  await act(async () => undefined);
}

function checklist(label: string): Array<[string | null, boolean]> {
  const group = host.querySelector(`[role=group][aria-label='${label}']`)!;
  return [...group.querySelectorAll("label")].map((l) => [l.textContent, (l.querySelector("input") as HTMLInputElement).checked]);
}

function field(label: string): HTMLTextAreaElement | HTMLInputElement {
  const found = [...host.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label));
  const control = found?.querySelector("textarea, input");
  if (!control) throw new Error(`no ${label} field`);
  return control as HTMLTextAreaElement | HTMLInputElement;
}

async function type(control: HTMLTextAreaElement | HTMLInputElement, value: string) {
  const proto = control instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(control, value);
    control.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function save() {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === "Save extension settings")!;
  await act(async () => button.click());
  await act(async () => undefined);
}

describe("the browser extension card", () => {
  it("shows the settings as stored", async () => {
    serve();
    await render();
    expect((host.querySelector("input[type=radio]:checked")?.closest("label")?.textContent ?? "").startsWith("Ask per site")).toBe(true);
    expect(field("Allowed sites").value).toBe("wiki.example.com");
    expect(field("Blocked sites").value).toBe("*.bank.example");
    expect(checklist("Models that may receive page content")).toEqual([
      ["GPT A · openai", false],
      ["GPT B · openai", true],
    ]);
  });

  it("needs nothing but its own settings, which come with the models to choose from", async () => {
    serve();
    await render();
    // Not the Models menu's list: an administrator of Chat Tools alone may lack it.
    expect(vi.mocked(api).mock.calls.map(([path]) => path)).toEqual(["/api/admin/extension/settings"]);
  });

  it("shows a selected model that is no longer on offer, and lets it be removed", async () => {
    serve({
      settings: { page_content_models: ["model::2", "model::4", "model::9"] },
      models: [
        ...MODELS,
        { ref: "model::4", label: "Old", provider: "openai", state: "disabled" },
        { ref: "model::9", label: "Model 9", provider: null, state: "deleted" },
      ],
    });
    await render();
    expect(checklist("Models that may receive page content")).toEqual([
      ["Old · openai — turned off; still limits the choice until removed", true],
      ["Model 9 — no longer exists; still limits the choice until removed", true],
      ["GPT A · openai", false],
      ["GPT B · openai", true],
    ]);
    const old = [...host.querySelectorAll("[aria-label='Models that may receive page content'] label")].find((l) =>
      l.textContent?.startsWith("Old"),
    )!;
    await act(async () => (old.querySelector("input") as HTMLInputElement).click());
    expect(checklist("Models that may receive page content").map(([text]) => text)).not.toContain(
      "Old · openai — turned off; still limits the choice until removed",
    );
    await save();
    expect(lastPut?.page_content_models).toEqual(["model::2", "model::9"]);
  });

  const ROUTER = { ref: "model::7", label: "Auto Router", provider: "openrouter", state: "ok", auto_router: true };

  it("never offers Auto Router as one of the agent's models", async () => {
    serve({ models: [...MODELS, ROUTER] });
    await render();
    expect(checklist("Models the agent may use").map(([text]) => text)).not.toContain("Auto Router · openrouter");
  });

  it("shows an Auto Router already chosen for the agent, so it can be removed", async () => {
    serve({ models: [...MODELS, ROUTER], settings: { agent_models: ["model::7"] } });
    await render();
    expect(checklist("Models the agent may use")).toContainEqual(["Auto Router · openrouter", true]);
  });

  it("shows a review model that is no longer on offer by name, and says it has to change", async () => {
    serve({
      settings: { agent_review_model: "model::4" },
      models: [...MODELS, { ref: "model::4", label: "Old", provider: "openai", state: "disabled" }],
    });
    await render();
    const review = host.querySelector("input[aria-label='Review model']") as HTMLInputElement;
    expect(review.value).toBe("Old · openai (turned off)");
    expect(host.textContent).toContain("The review model is turned off: choose another, or None.");
  });

  it("keeps Enter in the model search from submitting the form", async () => {
    const many = Array.from({ length: 9 }, (_, i) => ({ ref: `model::${i + 1}`, label: `M${i + 1}`, provider: "p", state: "ok" }));
    serve({ models: many });
    await render();
    const search = host.querySelector("input[aria-label='Search models that may receive page content']") as HTMLInputElement;
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    await act(async () => search.dispatchEvent(enter));
    expect(enter.defaultPrevented).toBe(true);
    expect(lastPut).toBeNull();
  });

  it("lets the steps be cleared and typed again, and checks them before saving", async () => {
    serve();
    await render();
    const steps = field("Most steps per task") as HTMLInputElement;
    await type(steps, "");
    expect(steps.value).toBe("");
    await type(steps, "40");
    await save();
    expect(lastPut?.agent_max_steps).toBe(40);

    lastPut = null;
    for (const value of ["", "3", "101", "7.5"]) {
      await type(field("Most steps per task"), value);
      await save();
      expect(lastPut).toBeNull();
      expect(host.querySelector(".alert-error")?.textContent).toBe("Most steps per task must be a whole number from 5 to 100.");
    }
  });

  it("saves what the administrator changed, with the site lists as lists", async () => {
    serve();
    await render();
    const allSites = [...host.querySelectorAll("input[type=radio]")].find((r) => r.closest("label")?.textContent?.startsWith("All sites"))!;
    await act(async () => (allSites as HTMLInputElement).click());
    await type(field("Allowed sites"), " wiki.example.com \n\n*.corp.example, intranet ");
    const gptA = [...host.querySelectorAll("[aria-label='Models that may receive page content'] label")].find((l) =>
      l.textContent?.startsWith("GPT A"),
    )!;
    await act(async () => (gptA.querySelector("input") as HTMLInputElement).click());
    await save();
    expect(lastPut).toEqual({
      ...SETTINGS,
      site_access: "all_sites",
      allowed_sites: ["wiki.example.com", "*.corp.example", "intranet"],
      page_content_models: ["model::2", "model::1"],
    });
    expect(host.textContent).toContain("Browser extension settings saved.");
  });

  it("turns full control on and saves it", async () => {
    serve();
    await render();
    const control = [...host.querySelectorAll("input[type=checkbox]")].find((c) => c.closest("label")?.textContent?.startsWith("Full control"))!;
    expect((control as HTMLInputElement).checked).toBe(false);
    await act(async () => (control as HTMLInputElement).click());
    await save();
    expect(lastPut).toEqual({ ...SETTINGS, full_control: true });
  });

  it("saves the read-only and protected site lists", async () => {
    serve();
    await render();
    await type(field("Read-only sites"), "wiki.example.com");
    await type(field("Protected sites"), "*.shaparak.ir, bank.example");
    await save();
    expect(lastPut).toMatchObject({
      read_only_sites: ["wiki.example.com"],
      protected_sites: ["*.shaparak.ir", "bank.example"],
    });
  });

  it("turns the whole extension off and back on", async () => {
    serve();
    await render();
    const toggle = [...host.querySelectorAll("input[type=checkbox]")].find((c) =>
      c.closest("label")?.textContent?.startsWith("Browser extension on for the organisation"),
    )!;
    expect((toggle as HTMLInputElement).checked).toBe(true);
    await act(async () => (toggle as HTMLInputElement).click());
    await save();
    expect(lastPut).toMatchObject({ enabled: false });
  });

  it("relaxes an approval by unticking its always-ask box", async () => {
    serve();
    await render();
    const send = [...host.querySelectorAll("input[type=checkbox]")].find((c) =>
      c.closest("label")?.textContent?.startsWith("Sending messages and emails"),
    )!;
    expect((send as HTMLInputElement).checked).toBe(true);
    await act(async () => (send as HTMLInputElement).click());
    await save();
    expect(lastPut).toMatchObject({ relaxed_approvals: ["send"] });
  });

  it("shows the server's reason when a setting cannot be saved", async () => {
    serve({
      put: () => {
        throw new Error("Blocked sites: 'https://x' is not usable (a host name only: no scheme, port or path).");
      },
    });
    await render();
    await type(field("Blocked sites"), "https://x");
    await save();
    expect(host.querySelector(".alert-error")?.textContent).toContain("is not usable");
    // What the administrator typed stays in the form to be corrected.
    expect(field("Blocked sites").value).toBe("https://x");
  });

  it("gives IT the ID, the update URL and the policy value to copy", async () => {
    serve();
    await render();
    expect(host.textContent).toContain("Current version: 1.0.0.3");
    const copy = [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "Copy Policy value")!;
    await act(async () => copy.click());
    expect(copyTextToClipboard).toHaveBeenCalledWith(DISTRIBUTION.gpo_value);
  });

  it("says why the extension cannot be handed out yet, and warns about an unreadable key", async () => {
    serve({
      distribution: {
        available: false,
        reason: "Set FRONTEND_URL first.",
        extension_id: null,
        update_url: null,
        gpo_value: null,
        key_status: "unreadable",
        key_message: "SECRET_KEY changed",
      },
    });
    await render();
    expect(host.textContent).toContain("Set FRONTEND_URL first.");
    expect(host.querySelector(".alert-error")?.textContent).toContain("SECRET_KEY changed");
    expect([...host.querySelectorAll("button")].some((b) => b.getAttribute("aria-label") === "Copy Policy value")).toBe(false);
  });

  it("lets a read-only administrator look but not change anything", async () => {
    readOnly.value = true;
    serve();
    await render();
    expect(field("Allowed sites").disabled).toBe(true);
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Save extension settings")).toBe(false);
  });

  it("reports a failed load", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Forbidden"));
    await render();
    expect(host.querySelector(".alert-error")?.textContent).toBe("Forbidden");
  });
});

describe("site lists as typed", () => {
  it("are one pattern per line (or comma), trimmed, blank lines dropped", () => {
    expect(siteLines(" a.example \n\n*.b.example, c\n")).toEqual(["a.example", "*.b.example", "c"]);
    expect(siteLines("")).toEqual([]);
  });
});

describe("the browser_control probe", () => {
  const VISION = [
    { ref: "model::1", label: "GPT A", provider: "openai", state: "ok", vision: true },
    { ref: "model::2", label: "GPT B", provider: "openai", state: "ok", vision: false },
  ];
  const row = (label: string) => [...host.querySelectorAll(".extension-admin__probes tbody tr")].find((r) => r.textContent?.startsWith(label))!;

  it("lists the models that read images, with their last result, and runs one on request", async () => {
    serve({
      models: VISION,
      probes: { "model::1": { model_ref: "model::1", ran_at: "2026-09-26T10:00:00Z", vision: true, tool_calling: true, hits: 1, trials: 3, passed: false, detail: "Clicked inside the button in 1 of 3 trials." } },
    });
    await render();
    expect(row("GPT A").textContent).toContain("Failed: 1 of 3");
    expect([...host.querySelectorAll(".extension-admin__probes tbody tr")]).toHaveLength(1);
    const run = row("GPT A").querySelector("button")!;
    expect(run.textContent).toBe("Run probe");
    await act(async () => run.click());
    await act(async () => undefined);
    expect(probed).toEqual(["model::1"]);
    expect(row("GPT A").textContent).toContain("Passed: 3 of 3");
    expect(host.querySelector(".extension-admin__probe--ok")).not.toBeNull();
  });

  it("says when a model never called the tool, and shows the failure of a probe that could not run", async () => {
    serve({ models: VISION, probes: { "model::1": { model_ref: "model::1", ran_at: "2026-09-26T10:00:00Z", vision: true, tool_calling: false, hits: 0, trials: 3, passed: false, detail: "no tool" } }, probe: () => Promise.reject(new Error("Your budget does not cover the probe.")) });
    await render();
    expect(row("GPT A").textContent).toContain("No tool call");
    await act(async () => row("GPT A").querySelector("button")!.click());
    await act(async () => undefined);
    expect(host.querySelector(".alert-error")?.textContent).toBe("The probe could not run: Your budget does not cover the probe.");
  });

  it("offers no button to a read-only administrator, and says when no model reads images", async () => {
    readOnly.value = true;
    serve({ models: VISION });
    await render();
    expect(row("GPT A").querySelector("button")).toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    readOnly.value = false;
    serve();
    await render();
    expect(host.textContent).toContain("No enabled chat model reads images.");
  });
});

describe("the numbers the card takes as text", () => {
  it("are checked against their range, by name", () => {
    expect(numberField("agent_max_minutes", " 30 ")).toEqual({ value: 30 });
    expect(numberField("agent_max_minutes", "0")).toEqual({ error: "Most minutes per task must be a whole number from 1 to 180." });
    expect(numberField("screenshots_kept", "2.5")).toMatchObject({ error: expect.stringContaining("Screenshots kept") });
    expect(numberField("min_browser_version", "115")).toMatchObject({ error: expect.stringContaining("116 to 999") });
  });

  it("let the daily limit be empty, meaning none", () => {
    expect(numberField("agent_runs_per_day", "")).toEqual({ value: null });
    expect(numberField("agent_runs_per_day", "abc")).toEqual({ error: "Runs per person per day must be a whole number from 1 to 1000, or empty." });
  });
});

describe("the sections added for R1", () => {
  const checkbox = (label: string) =>
    [...host.querySelectorAll("input[type=checkbox]")].find((c) => c.closest("label")?.textContent?.startsWith(label)) as HTMLInputElement;

  it("shows the limits and the switches as stored, and saves what changed", async () => {
    serve({ settings: { agent_max_minutes: 45, agent_runs_per_day: 12, save_runs: false } });
    await render();
    expect((field("Most minutes per task") as HTMLInputElement).value).toBe("45");
    expect((field("Runs per person per day") as HTMLInputElement).value).toBe("12");
    expect(checkbox("Save finished runs").checked).toBe(false);
    expect(checkbox("Plan mode").checked).toBe(true);
    await type(field("Most tabs per task"), "4");
    await type(field("Runs per person per day"), "");
    await act(async () => checkbox("Require the newest package").click());
    await act(async () => checkbox("Screenshots of other sites may go").click());
    expect(checkbox("A screenshot after every change").checked).toBe(true);
    await act(async () => checkbox("A screenshot after every change").click());
    await save();
    expect(lastPut).toMatchObject({
      screenshot_after_action: false,
      agent_max_minutes: 45,
      agent_max_tabs: 4,
      agent_runs_per_day: null,
      require_newest_package: true,
      external_screenshots: false,
      save_runs: false,
      min_browser_version: 116,
    });
  });

  it("refuses a limit that is missing before anything is sent (out of range, the browser's own check stops the form)", async () => {
    serve();
    await render();
    await type(field("Most minutes per task"), "");
    await save();
    expect(lastPut).toBeNull();
    expect(host.querySelector(".alert-error")?.textContent).toBe("Most minutes per task must be a whole number from 1 to 180.");
  });

  it("offers the modes that are on as the default, and falls back to Ask when Plan is turned off", async () => {
    serve();
    await render();
    const select = host.querySelector("select[aria-label='Default mode']") as HTMLSelectElement;
    expect(select.value).toBe("plan");
    expect((select.querySelector("option[value=auto]") as HTMLOptionElement).disabled).toBe(true);
    await act(async () => checkbox("Plan mode").click());
    expect(select.value).toBe("ask");
    expect((select.querySelector("option[value=plan]") as HTMLOptionElement).disabled).toBe(true);
    await save();
    expect(lastPut).toMatchObject({ plan_mode: false, agent_default_mode: "ask" });
  });

  it("lists the connections, marks the ones that look internal, and ticks them on request", async () => {
    serve();
    await render();
    const rows = checklist("Connections inside the organisation");
    expect(rows).toEqual([
      [expect.stringContaining("OpenAI"), false],
      [expect.stringContaining("Ollama box"), false],
    ]);
    expect(rows[1][0]).toContain("looks internal");
    expect(rows[0][0]).not.toContain("looks internal");
    const tick = [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Tick the one that looks internal"))!;
    await act(async () => tick.click());
    expect(checklist("Connections inside the organisation")[1][1]).toBe(true);
    await save();
    expect(lastPut).toMatchObject({ internal_connections: [2] });
  });
});
