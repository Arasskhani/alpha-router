/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: async () => true }) }));

import { api } from "../../api";
import Connections from "./Connections";

const MODEL = {
  id: 1,
  name: "OpenRouter",
  kind: "models",
  provider_type: "openrouter",
  base_url: null,
  is_active: true,
  sync_interval_hours: 6,
  last_sync_at: null,
  created_at: null,
  updated_at: null,
  usage_usd: 1.5,
  api_key_masked: "sk-…abcd",
};
const SEARCH = {
  id: 2,
  name: "Brave",
  kind: "web_search",
  provider_type: "brave",
  base_url: null,
  is_active: true,
  usage_usd: 0.02,
  api_key_masked: "BSA…wxyz",
  priority: 10,
  price_per_request_usd: 0.005,
  config: {},
};
const OVERVIEW = {
  settings: { duckduckgo_fallback: true },
  plan: [
    { label: "Brave", provider: "brave", connection_id: 2 },
    { label: "DuckDuckGo", provider: "duckduckgo", connection_id: null },
  ],
  available: true,
};

let host: HTMLDivElement;
let root: Root;
let calls: { url: string; init?: RequestInit }[];

beforeEach(() => {
  calls = [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/admin/connections") return [MODEL, SEARCH];
    if (url === "/api/admin/web-search" && init?.method === "PUT") {
      return { ...OVERVIEW, settings: { duckduckgo_fallback: false }, plan: [OVERVIEW.plan[0]] };
    }
    if (url === "/api/admin/web-search") return OVERVIEW;
    if (url === "/api/admin/web-search/test") return { ok: true, count: 4, elapsed_ms: 321, results: [{ title: "First", url: "https://a.example" }] };
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
        <Connections />
      </MemoryRouter>,
    );
  });
}

function tab(name: RegExp): HTMLButtonElement {
  return [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => name.test(b.textContent ?? ""))!;
}

function button(text: string | RegExp): HTMLButtonElement {
  return [...host.ownerDocument.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof text === "string" ? b.textContent === text : text.test(b.textContent ?? ""),
  )!;
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("the Connections page", () => {
  it("keeps model providers and web search services in tabs of their own", async () => {
    await render();
    expect(tab(/Model providers \(1\)/)).toBeTruthy();
    expect(tab(/Web search \(1\)/)).toBeTruthy();
    expect(host.querySelector("table")!.textContent).toContain("OpenRouter");
    expect(host.querySelector("table")!.textContent).not.toContain("Brave");
    expect(button(/New model connection/)).toBeTruthy();
    await act(async () => tab(/Web search/).click());
    expect(host.querySelector("table")!.textContent).toContain("Brave Search");
    expect(host.querySelector("table")!.textContent).not.toContain("OpenRouter");
    expect(host.querySelector('[data-testid="web-search-order"]')!.textContent).toBe("A search asks, in order: Brave → DuckDuckGo.");
    expect(button(/New web search connection/)).toBeTruthy();
  });

  it("names the model key as one and warns when a search key is typed there", async () => {
    await render();
    await act(async () => button(/New model connection/).click());
    const dialog = host.ownerDocument.querySelector(".connection-form")!;
    expect(dialog.textContent).toContain("Model API key");
    const key = dialog.querySelector<HTMLInputElement>('input[type="password"]')!;
    await type(key, "tvly-123");
    expect(dialog.textContent).toContain("This looks like a Tavily key, not a model provider's");
  });

  it("offers only search services in the web search form, with the fields each needs", async () => {
    await render();
    await act(async () => tab(/Web search/).click());
    await act(async () => button(/New web search connection/).click());
    const form = host.ownerDocument.querySelector(".connection-form")!;
    const services = [...form.querySelectorAll<HTMLInputElement>('input[type="radio"]')].map((r) => r.value);
    expect(services).toEqual(["brave", "tavily", "google_pse", "searxng", "duckduckgo"]);
    expect(form.textContent).toContain("Web Search API key");
    await type(form.querySelector<HTMLInputElement>('input[type="password"]')!, "sk-proj-abc");
    expect(form.textContent).toContain("looks like a model provider's API key");
    // Google needs its engine id; SearXNG its address and no key.
    await act(async () => form.querySelector<HTMLInputElement>('input[value="google_pse"]')!.click());
    expect(form.textContent).toContain("Search engine id (cx)");
    await act(async () => form.querySelector<HTMLInputElement>('input[value="searxng"]')!.click());
    expect(form.textContent).toContain("SearXNG address");
    expect(form.querySelector('input[type="password"]')).toBeNull();
  });

  it("tests a draft with what the form holds and saves it as a web search connection", async () => {
    await render();
    await act(async () => tab(/Web search/).click());
    await act(async () => button(/New web search connection/).click());
    const form = host.ownerDocument.querySelector(".connection-form")!;
    await type(form.querySelector<HTMLInputElement>('input[type="password"]')!, "BSA-key");
    await act(async () => button("Test").click());
    const test = calls.find((c) => c.url === "/api/admin/web-search/test")!;
    expect(JSON.parse(String(test.init!.body))).toMatchObject({ provider_type: "brave", api_key: "BSA-key" });
    expect(form.textContent).toContain("The search worked: 4 results in 321 ms — first: First.");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const created = calls.find((c) => c.url === "/api/admin/connections" && c.init?.method === "POST")!;
    expect(JSON.parse(String(created.init!.body))).toMatchObject({
      kind: "web_search",
      provider_type: "brave",
      name: "Brave Search",
      api_key: "BSA-key",
      priority: 100,
      price_per_request_usd: 0.005,
    });
  });

  it("turns the DuckDuckGo fallback off", async () => {
    await render();
    await act(async () => tab(/Web search/).click());
    const box = host.querySelector<HTMLInputElement>(".web-search-fallback input[type=checkbox]")!;
    expect(box.checked).toBe(true);
    await act(async () => box.click());
    const put = calls.find((c) => c.url === "/api/admin/web-search" && c.init?.method === "PUT")!;
    expect(JSON.parse(String(put.init!.body))).toEqual({ duckduckgo_fallback: false });
    expect(host.querySelector('[data-testid="web-search-order"]')!.textContent).toBe("A search asks, in order: Brave.");
  });
});
