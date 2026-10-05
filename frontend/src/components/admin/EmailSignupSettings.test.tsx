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

import { api } from "../../api";
import EmailSignupSettings, { type EmailSignupView } from "./EmailSignupSettings";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const VIEW: EmailSignupView = {
  enabled: false,
  allowed_domains: ["example.com"],
  default_plan_id: null,
  reset_enabled: false,
  smtp_configured: true,
  plans: [
    { id: 3, name: "Starter", monthly_budget_usd: 10 },
    { id: 4, name: "Team", monthly_budget_usd: 50 },
  ],
  signups_last_30_days: 7,
};

let host: HTMLDivElement;
let root: Root;
let lastPut: Record<string, unknown> | null;

function serve(view: Partial<EmailSignupView> = {}, putError?: Error) {
  vi.mocked(api).mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      lastPut = JSON.parse(String(init.body)) as Record<string, unknown>;
      if (putError) throw putError;
      return { ...VIEW, ...view, ...lastPut } as never;
    }
    return { ...VIEW, ...view } as never;
  });
}

beforeEach(() => {
  readOnly.value = false;
  lastPut = null;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.mocked(api).mockReset();
});

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <EmailSignupSettings />
      </MemoryRouter>,
    );
  });
}

function field<T extends HTMLElement>(selector: string): T {
  const el = host.querySelector<T>(selector);
  if (!el) throw new Error(`no ${selector}`);
  return el;
}

function checkbox(label: string): HTMLInputElement {
  const found = [...host.querySelectorAll("label")].find((l) => l.textContent?.includes(label));
  const input = found?.querySelector<HTMLInputElement>("input[type=checkbox]");
  if (!input) throw new Error(`no checkbox "${label}"`);
  return input;
}

async function typeInto(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set?.call(select, value);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(el: HTMLElement) {
  await act(async () => el.click());
}

function button(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === text);
  if (!found) throw new Error(`no button "${text}"`);
  return found;
}

describe("Email sign-up settings", () => {
  it("shows the saved settings and how many accounts were made", async () => {
    serve();
    await render();
    expect(host.textContent).toContain("example.com");
    expect(host.textContent).toContain("Accounts created in the last 30 days: 7");
    expect(checkbox("Allow people to create an account").checked).toBe(false);
    expect(field<HTMLSelectElement>("#email-signup-plan").value).toBe("");
    expect(host.textContent).toContain("cannot spend until an administrator assigns one");
  });

  it("saves the switches, the domains and the plan", async () => {
    serve();
    await render();
    await click(checkbox("Allow people to create an account"));
    await click(checkbox("reset a forgotten password"));
    await typeInto(field<HTMLInputElement>("#email-signup-domain"), "@Corp.Example, lab.example");
    await click(button("Add"));
    await click(field<HTMLButtonElement>('[aria-label="Remove example.com"]'));
    await choose(field<HTMLSelectElement>("#email-signup-plan"), "4");
    expect(host.textContent).toContain("New accounts get Team");
    await click(button("Save email sign-up"));
    expect(lastPut).toEqual({
      enabled: true,
      allowed_domains: ["corp.example", "lab.example"],
      default_plan_id: 4,
      reset_enabled: true,
    });
    expect(host.textContent).toContain("Email sign-up settings saved.");
  });

  it("does not send back a default plan that no longer exists", async () => {
    serve({ default_plan_id: 99 });
    await render();
    expect(field<HTMLSelectElement>("#email-signup-plan").value).toBe("");
    await click(button("Save email sign-up"));
    expect(lastPut?.default_plan_id).toBeNull();
  });

  it("keeps a domain that was typed but not added", async () => {
    serve();
    await render();
    await typeInto(field<HTMLInputElement>("#email-signup-domain"), "late.example");
    await click(button("Save email sign-up"));
    expect(lastPut?.allowed_domains).toEqual(["example.com", "late.example"]);
  });

  it("warns that with no domains anyone may sign up", async () => {
    serve({ enabled: true, allowed_domains: [], default_plan_id: 3 });
    await render();
    expect(host.textContent).toContain("anyone with an email address can create an account and spend from the default plan");
  });

  it("says SMTP must be set up first", async () => {
    serve({ smtp_configured: false });
    await render();
    const alert = [...host.querySelectorAll("[role=alert]")].find((el) => el.textContent?.includes("SMTP"));
    expect(alert?.querySelector("a")?.getAttribute("href")).toBe("/admin/smtp");
  });

  it("shows the server's refusal", async () => {
    serve({}, new Error("Set up the SMTP server before turning on email sign-up."));
    await render();
    await click(checkbox("Allow people to create an account"));
    await click(button("Save email sign-up"));
    expect(host.textContent).toContain("Set up the SMTP server before turning on email sign-up.");
    expect(host.textContent).not.toContain("Email sign-up settings saved.");
  });

  it("only shows the settings to a read-only administrator", async () => {
    readOnly.value = true;
    serve();
    await render();
    expect(checkbox("Allow people to create an account").disabled).toBe(true);
    expect(host.querySelector("button[type=submit]")).toBeNull();
    expect(host.querySelector('[aria-label="Remove example.com"]')).toBeNull();
  });
});
