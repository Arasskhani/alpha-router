/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../api", () => ({ api: vi.fn(), formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
vi.mock("../../lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));

import { api } from "../../api";
import { copyTextToClipboard } from "../../lib/clipboard";
import ExtensionSettingsCard, { siteLines } from "./ExtensionSettingsCard";

const SETTINGS = {
  site_access: "per_site",
  allowed_sites: ["wiki.example.com"],
  blocked_sites: ["*.bank.example"],
  page_content_models: ["model::2"],
  agent_models: [],
  agent_max_steps: 25,
  agent_auto_mode: false,
  agent_review_model: null,
};
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

let host: HTMLDivElement;
let root: Root;
let lastPut: Record<string, unknown> | null;

function serve(
  overrides: {
    settings?: object;
    models?: object[];
    distribution?: object;
    put?: (body: Record<string, unknown>) => unknown;
  } = {},
) {
  const models = overrides.models ?? MODELS;
  vi.mocked(api).mockImplementation((async (path: string, init?: RequestInit) => {
    if (path !== "/api/admin/extension/settings") throw new Error(`unexpected request to ${path}`);
    if (init?.method === "PUT") {
      lastPut = JSON.parse(String(init.body));
      if (overrides.put) return overrides.put(lastPut!);
      return { settings: { ...SETTINGS, ...lastPut }, models, distribution: DISTRIBUTION };
    }
    return {
      settings: { ...SETTINGS, ...overrides.settings },
      models,
      distribution: { ...DISTRIBUTION, ...overrides.distribution },
    };
  }) as never);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  readOnly.value = false;
  lastPut = null;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render() {
  await act(async () => root.render(<ExtensionSettingsCard />));
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
