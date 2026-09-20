/**
 * @vitest-environment happy-dom
 *
 * Creating the personal key is one act in one dialog: name it, create it, copy
 * it. The name used to sit on the settings panel itself, in a card that looked
 * like the editable rows around it but was really half of a create form — and
 * the only thing the dialog did was show the secret afterwards.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), prompt: vi.fn() }),
}));

import { api } from "../api";
import PersonalApiKeyPanel from "./PersonalApiKeyPanel";

const BUDGET = { monthly_budget_usd: 15, used_usd: 0.95, remaining_usd: 14.05 };

function answerWith({ keys = [], budget = BUDGET }: { keys?: unknown[]; budget?: unknown } = {}) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path.includes("/api-keys/list")) return keys;
    if (path.includes("/budget")) return budget;
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
  document.body.innerHTML = "";
});

async function render() {
  await act(async () => {
    root.render(<PersonalApiKeyPanel />);
  });
}

function button(label: string) {
  return [...document.querySelectorAll("button")].find((b) => b.textContent === label);
}

function click(label: string) {
  return act(async () => button(label)?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

/** React tracks the value itself; a plain assignment does not reach onChange. */
async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function nameInput() {
  return [...document.querySelectorAll("input")].find(
    (i) => i.getAttribute("aria-label") === "Key name" || !i.readOnly,
  );
}

describe("the personal API key panel", () => {
  it("offers a single action and no stray field", async () => {
    answerWith();
    await render();
    expect(button("Create API key")).toBeTruthy();
    expect(host.textContent).not.toContain("Key name");
  });

  it("asks for the name in the dialog the button opens", async () => {
    answerWith();
    await render();
    await click("Create API key");
    // The dialog's own action is labelled differently from the one that opened it.
    expect(button("Create key")).toBeTruthy();
    expect(document.body.textContent).toContain("Create personal API key");
    expect(document.body.textContent).toContain("Key name");
    expect(nameInput()?.value).toBe("Personal API Key");
  });

  it("creates with the name that was typed and shows the key in the same dialog", async () => {
    answerWith();
    await render();
    await click("Create API key");

    await type(nameInput() as HTMLInputElement, "Laptop");

    vi.mocked(api).mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === "/api/user/api-keys" && init?.method === "POST") {
        return { id: 1, name: "Laptop", api_key: "ar_secret_value", prefix: "ar_sec", url: "https://x/v1" };
      }
      if (path.includes("/api-keys/list")) return [];
      if (path.includes("/budget")) return BUDGET;
      throw new Error(`unexpected ${path}`);
    });
    await click("Create key");

    const posted = vi.mocked(api).mock.calls.find((call) => String(call[0]) === "/api/user/api-keys");
    expect(JSON.parse(String((posted?.[1] as { body?: string })?.body))).toEqual({ name: "Laptop" });
    expect(document.body.textContent).toContain("Your personal API key");
    expect(document.body.textContent).toContain("You will not be able to view it again");
  });

  it("forgets the secret once the dialog is closed", async () => {
    answerWith();
    await render();
    await click("Create API key");
    vi.mocked(api).mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === "/api/user/api-keys" && init?.method === "POST") {
        return { id: 1, name: "n", api_key: "ar_secret_value", prefix: "ar_sec", url: "https://x/v1" };
      }
      if (path.includes("/api-keys/list")) return [];
      if (path.includes("/budget")) return BUDGET;
      throw new Error(`unexpected ${path}`);
    });
    await click("Create key");
    await click("Done");

    expect(document.body.textContent).not.toContain("ar_secret_value");
    await click("Create API key");
    expect(document.body.textContent).not.toContain("ar_secret_value");
    expect(nameInput()?.value).toBe("Personal API Key");
  });

  it("keeps a failed create readable, in the dialog rather than behind it", async () => {
    answerWith();
    await render();
    await click("Create API key");
    vi.mocked(api).mockRejectedValue(new Error("quota exceeded"));
    await click("Create key");

    const alert = document.querySelector(".settings-error");
    expect(alert?.textContent).toContain("quota exceeded");
    expect(document.body.textContent).toContain("Key name");
  });

  it("will not open at all without a budget, and says why", async () => {
    answerWith({ budget: { monthly_budget_usd: 0, used_usd: 0, remaining_usd: null } });
    await render();
    expect(button("Create API key")?.disabled).toBe(true);
    expect(host.textContent).toContain("Ask an administrator to assign a monthly budget plan");
  });

  it("shows the existing key instead of the create button", async () => {
    answerWith({
      keys: [
        {
          id: 1,
          name: "Laptop",
          prefix: "ar_abc",
          url: "https://x/v1",
          is_active: true,
          created_at: null,
          last_used_at: null,
        },
      ],
    });
    await render();
    expect(host.textContent).toContain("Laptop");
    expect(button("Create API key")).toBeUndefined();
    expect(button("Revoke")).toBeTruthy();
  });
});
