/**
 * @vitest-environment happy-dom
 *
 * Admin › Exchange EWS › Settings: bounds are checked before Save, Save sends
 * the whole object, a server refusal (422 `invalid_settings`) is shown next to
 * the field it is about, the TLS warning and the login example follow the
 * form, the detection model comes from the model picker, and Test connection
 * runs with the saved settings and empties the password after every run.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  authFetch: vi.fn(),
  api: vi.fn(async () => []),
  bootstrapSession: vi.fn(async () => ({})),
  formatApiError: (e: unknown) => String(e),
}));
const dialogs = vi.hoisted(() => ({
  confirm: vi.fn(async (_options: { title?: string; message: string }) => true as boolean | "secondary"),
  prompt: vi.fn(async () => null as string | null),
}));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => dialogs }));
const sessionState = vi.hoisted(() => ({ value: { role: "super_admin", roles: ["super_admin"] } as Record<string, unknown> }));
vi.mock("../../hooks/useCachedSession", () => ({ useCachedSession: () => sessionState.value }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch, bootstrapSession } from "../../api";
import { TEST_FAILED, fakeExchangeApi, json, makeSettings, type Call } from "../../components/exchange/testFixtures";
import type { ExchangeSettings } from "../../lib/exchangeMail";
import ExchangeEws from "./ExchangeEws";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];

function useApi(override?: Parameters<typeof fakeExchangeApi>[1], settings?: Parameters<typeof fakeExchangeApi>[2]) {
  vi.mocked(authFetch).mockImplementation(fakeExchangeApi(calls, override, settings) as typeof authFetch);
}

beforeEach(() => {
  readOnly.value = false;
  sessionState.value = { role: "super_admin", roles: ["super_admin"] };
  dialogs.confirm.mockReset();
  dialogs.confirm.mockResolvedValue(true);
  calls = [];
  vi.mocked(authFetch).mockReset();
  vi.mocked(bootstrapSession).mockClear();
  useApi();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function settle() {
  for (let i = 0; i < 4; i += 1) await act(async () => undefined);
}

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/admin/exchange-ews?tab=settings"]}>
        <Routes>
          <Route path="/admin/exchange-ews" element={<ExchangeEws />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await settle();
}

const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === text);
const input = (id: string) => host.querySelector<HTMLInputElement & HTMLTextAreaElement>(`#${id}`)!;
const check = (title: string) =>
  [...host.querySelectorAll<HTMLLabelElement>("label.ews-admin-check")]
    .find((l) => l.querySelector(".ews-admin-check__title")?.textContent === title)!
    .querySelector<HTMLInputElement>("input")!;
const fieldOf = (id: string) => input(id).closest<HTMLElement>(".ews-admin-field, .ews-admin-number")!;

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function click(el: HTMLElement) {
  await act(async () => el.click());
  await settle();
}

const savedBody = () => calls.filter((c) => c.url.endsWith("/settings") && c.method === "PUT").at(-1)?.body as ExchangeSettings;

describe("Exchange EWS settings", () => {
  it("checks the bounds before saving and sends the whole object", async () => {
    await render();
    expect(input("ews-poll").value).toBe("5");
    expect(button("Save settings")!.disabled).toBe(true);

    await type(input("ews-poll"), "1");
    expect(fieldOf("ews-poll").textContent).toContain("Enter a whole number from 2 to 60.");
    expect(button("Save settings")!.disabled).toBe(true);
    expect(host.textContent).toContain("1 field needs a fix before saving.");
    await type(input("ews-poll"), "10");
    await type(input("ews-url"), "http://mail.corp.example");
    expect(fieldOf("ews-url").textContent).toContain("Enter an https address");
    await type(input("ews-url"), "https://mail.corp.example");
    await act(async () => check("Find meeting times").click());
    expect(host.textContent).toContain("Unsaved changes.");

    await click(button("Save settings")!);
    expect(savedBody()).toEqual({
      ...makeSettings().settings,
      poll_minutes: 10,
      ews_url: "https://mail.corp.example",
      allow_free_time: false,
    });
    expect(host.textContent).toContain("Settings saved.");
    // Enabled did not change: this account's own menus stay as they are.
    expect(bootstrapSession).not.toHaveBeenCalled();
  });

  it("shows a 422 invalid_settings refusal next to its field and clears it on the next edit", async () => {
    useApi((url, method) =>
      url.endsWith("/settings") && method === "PUT"
        ? json(422, { detail: { code: "invalid_settings", message: "One of the CA certificates could not be read." } })
        : undefined,
    );
    await render();
    await type(input("ews-ca"), "-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----");
    expect(fieldOf("ews-ca").textContent).toContain("1 certificate, trusted besides the system's own.");
    await click(button("Save settings")!);

    const error = fieldOf("ews-ca").querySelector(".ews-admin-field-error");
    expect(error?.textContent).toBe("One of the CA certificates could not be read.");
    expect(input("ews-ca").getAttribute("aria-invalid")).toBe("true");
    // Shown at the field, not above the form.
    expect(host.querySelector(".ews-admin-settings-wrap > .alert-error")).toBeNull();
    expect(host.textContent).not.toContain("Settings saved.");

    await type(input("ews-ca"), "");
    expect(fieldOf("ews-ca").querySelector(".ews-admin-field-error")).toBeNull();
  });

  it("names the setting's own key in a refusal and shows it at that field", async () => {
    useApi((url, method) =>
      url.endsWith("/settings") && method === "PUT"
        ? json(422, { detail: { code: "invalid_settings", message: "timeout_s must be a whole number from 5 to 120." } })
        : undefined,
    );
    await render();
    await type(input("ews-timeout"), "40");
    await click(button("Save settings")!);
    expect(fieldOf("ews-timeout").textContent).toContain("timeout_s must be a whole number from 5 to 120.");
  });

  it("shows a refusal it cannot place above the form", async () => {
    useApi((url, method) =>
      url.endsWith("/settings") && method === "PUT"
        ? json(422, { detail: { code: "invalid_settings", message: "Send the settings as an object." } })
        : undefined,
    );
    await render();
    await type(input("ews-poll"), "6");
    await click(button("Save settings")!);
    expect(host.querySelector(".ews-admin-settings-wrap > .alert-error")?.textContent).toBe(
      "Send the settings as an object.",
    );
  });

  it("refreshes this account's menus when Exchange EWS is turned on or off", async () => {
    await render();
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Exchange EWS on"]')!.click());
    await click(button("Save settings")!);
    expect(savedBody().enabled).toBe(false);
    expect(bootstrapSession).toHaveBeenCalledWith(true);
    expect(host.querySelector(".ews-admin-off")?.textContent).toContain("Exchange EWS is off.");
  });

  it("warns in red when the certificate is not verified", async () => {
    await render();
    expect(host.querySelector('[data-testid="ews-tls-warning"]')).toBeNull();
    await act(async () => check("Verify the Exchange server's certificate").click());
    const warning = host.querySelector('[data-testid="ews-tls-warning"]')!;
    expect(warning.classList.contains("alert-error")).toBe(true);
    expect(warning.textContent).toContain("Certificate not verified.");
  });

  it("explains the address and the login with examples from the directory", async () => {
    await render();
    expect(fieldOf("ews-url").textContent).toContain("https://mail.corp.example/EWS/Exchange.asmx");
    expect(host.querySelector("#ews-login-example")?.textContent).toContain("Your own login would be CORP\\m.arasskhani.");
    expect(input("ews-netbios").placeholder).toBe("CORP");
    expect(fieldOf("ews-netbios").textContent).toContain("Blank: CORP, from the LDAP settings.");

    const upn = host.querySelector<HTMLInputElement>('input[name="ews-login-format"][value="upn"]')!;
    await act(async () => upn.click());
    expect(input("ews-upn").placeholder).toBe("corp.example");
    expect(host.querySelector("#ews-netbios")).toBeNull();
    expect(host.querySelector("#ews-login-example")?.textContent).toContain(
      "Your own login would be m.arasskhani@corp.example (after saving).",
    );
  });

  it("says the mailbox limit counts Full Access mailboxes, not a person's own", async () => {
    await render();
    expect(fieldOf("ews-max-mailboxes").textContent).toContain("Full Access mailboxes per person");
    expect(fieldOf("ews-max-mailboxes").textContent).toContain("Besides their own mailbox, which is not counted.");
  });

  it("picks the detection model with the model picker and stores its id", async () => {
    await render();
    const model = host.querySelector<HTMLInputElement>('input[name="ews-detection"][value="model"]')!;
    await act(async () => model.click());
    await settle();
    expect(calls.some((c) => c.url === "/api/admin/models")).toBe(true);
    expect(fieldOf("ews-detection-model").textContent).toContain("Choose a model, or use the rules.");
    expect(button("Save settings")!.disabled).toBe(true);

    await act(async () => {
      input("ews-detection-model").focus();
      input("ews-detection-model").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    });
    const options = [...host.querySelectorAll<HTMLButtonElement>('[role="option"]')].map((o) => o.textContent);
    // Enabled text models only.
    expect(options).toEqual(["Not chosen", "GPT-4o mini · openai"]);
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>('[role="option"]')][1].click());
    await click(button("Save settings")!);
    expect(savedBody()).toMatchObject({ detection: "model", detection_model: "7" });
  });
});

describe("where passwords are sent", () => {
  const ENDPOINT = ["ews-url", "ews-autodiscover", "ews-ca"];

  it("is read-only, with a note, for a writer who is not a Super Admin; the rest stays open", async () => {
    sessionState.value = { role: "integrations_administrator", roles: ["integrations_administrator"] };
    await render();
    for (const id of ENDPOINT) {
      expect(input(id).disabled, id).toBe(true);
      expect(input(id).getAttribute("aria-describedby"), id).toContain("ews-endpoint-note");
    }
    expect(check("Verify the Exchange server's certificate").disabled).toBe(true);
    expect(host.querySelector("#ews-endpoint-note")?.textContent).toContain(
      "Only a Super Admin can change where Exchange passwords are sent.",
    );
    expect(input("ews-poll").disabled).toBe(false);
    expect(check("Find meeting times").disabled).toBe(false);
    await act(async () => check("Find meeting times").click());
    await click(button("Save settings")!);
    expect(dialogs.confirm).not.toHaveBeenCalled();
    expect(savedBody()).toMatchObject({ allow_free_time: false });
  });

  it("is open to a Super Admin (and a full administrator), without the note", async () => {
    for (const roles of [["super_admin"], ["full_administrator"]]) {
      sessionState.value = { role: roles[0], roles };
      await render();
      for (const id of ENDPOINT) expect(input(id).disabled, `${roles[0]} ${id}`).toBe(false);
      expect(host.querySelector("#ews-endpoint-note")).toBeNull();
    }
  });

  it.each([
    ["the EWS address", async () => type(input("ews-url"), "https://mail2.corp.example/EWS/Exchange.asmx")],
    ["the login format", async () => act(async () => host.querySelector<HTMLInputElement>('input[name="ews-login-format"][value="upn"]')!.click())],
    ["the NetBIOS domain", async () => type(input("ews-netbios"), "CORP2")],
    ["certificate checks", async () => act(async () => check("Verify the Exchange server's certificate").click())],
  ])("asks before saving a change to %s: everyone types their password again", async (_name, change) => {
    await render();
    await change();
    dialogs.confirm.mockResolvedValueOnce(false);
    await click(button("Save settings")!);
    expect(dialogs.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Everyone who connected a mailbox will have to type their password again." }),
    );
    expect(savedBody()).toBeUndefined();
    await click(button("Save settings")!);
    expect(dialogs.confirm).toHaveBeenCalledTimes(2);
    expect(savedBody()).toBeTruthy();
    expect(host.textContent).toContain("Settings saved.");
  });

  it("does not ask for a change that keeps the passwords working", async () => {
    await render();
    await type(input("ews-poll"), "10");
    await click(button("Save settings")!);
    expect(dialogs.confirm).not.toHaveBeenCalled();
    expect(savedBody()).toMatchObject({ poll_minutes: 10 });
  });

  it("shows the server's super_admin_only refusal with the controls it is about", async () => {
    useApi((url, method) =>
      url.endsWith("/settings") && method === "PUT"
        ? json(403, { detail: { code: "super_admin_only", message: "Only a Super Admin can change where Exchange passwords are sent." } })
        : undefined,
    );
    await render();
    await type(input("ews-url"), "https://mail2.corp.example/EWS/Exchange.asmx");
    await click(button("Save settings")!);
    const connection = host.querySelector(".ews-admin-card--connection")!;
    const alert = connection.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe("Only a Super Admin can change where Exchange passwords are sent.");
    expect(host.textContent).not.toContain("Settings saved.");
    await click(button("Discard")!);
    expect(connection.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("Test connection", () => {
  async function fill(login: string, password: string, email = "") {
    await type(input("ews-test-login"), login);
    await type(input("ews-test-password"), password);
    if (email) await type(input("ews-test-email"), email);
  }

  it("runs with the saved settings, lists the steps and what it found, and empties the password", async () => {
    await render();
    expect(host.textContent).toContain("Nothing is stored");
    expect(input("ews-test-password").type).toBe("password");
    expect(input("ews-test-password").getAttribute("autocomplete")).toBe("new-password");
    expect(button("Run test")!.disabled).toBe(true);

    await fill("CORP\\s.karimi", "Secret-1", "s.karimi@corp.example");
    await click(button("Run test")!);

    const post = calls.find((c) => c.url.endsWith("/test"))!;
    expect(post.method).toBe("POST");
    expect(post.body).toEqual({ login: "CORP\\s.karimi", password: "Secret-1", email: "s.karimi@corp.example" });
    const result = host.querySelector('[data-testid="ews-test-result"]')!;
    expect(result.textContent).toContain("The test passed");
    const steps = [...result.querySelectorAll(".ews-admin-step")];
    expect(steps).toHaveLength(5);
    expect(steps.every((s) => s.classList.contains("ews-admin-step--ok"))).toBe(true);
    expect(steps[1].textContent).toContain("Exchange accepted CORP\\s.karimi");
    expect(result.textContent).toContain("Mailbox found");
    expect(result.textContent).toContain("Sara Karimi");
    expect(result.textContent).toContain("Full Access mailboxes · 2 found");
    expect(result.textContent).toContain("finance@corp.example");
    expect(result.textContent).toContain("Human Resources");
    expect(input("ews-test-password").value).toBe("");
    expect(input("ews-test-login").value).toBe("CORP\\s.karimi");
  });

  it("marks the failing step with a cross and its detail, and still empties the password", async () => {
    useApi((url) => (url.endsWith("/test") ? TEST_FAILED : undefined));
    await render();
    await fill("CORP\\s.karimi", "wrong");
    await click(button("Run test")!);

    const post = calls.find((c) => c.url.endsWith("/test"))!;
    expect(post.body).toEqual({ login: "CORP\\s.karimi", password: "wrong" });
    const result = host.querySelector('[data-testid="ews-test-result"]')!;
    expect(result.textContent).toContain("The test stopped at the step marked with a cross.");
    const failed = result.querySelector(".ews-admin-step--fail")!;
    expect(failed.textContent).toContain("Sign in");
    expect(failed.textContent).toContain("Exchange did not accept the user name or password");
    expect(result.textContent).not.toContain("Mailbox found");
    expect(result.textContent).not.toContain("Full Access mailboxes");
    expect(input("ews-test-password").value).toBe("");
  });

  it("shows a warning, not a failure, when only Autodiscover fails", async () => {
    useApi((url) =>
      url.endsWith("/test")
        ? {
            ok: true,
            steps: [
              { key: "login", label: "Sign in", ok: true, detail: "" },
              { key: "autodiscover", label: "Full Access mailboxes", ok: false, detail: "Autodiscover did not answer" },
            ],
            mailbox: { smtp: "s.karimi@corp.example", display_name: "Sara Karimi" },
            full_access: [],
          }
        : undefined,
    );
    await render();
    await fill("CORP\\s.karimi", "Secret-1");
    await click(button("Run test")!);
    expect(host.querySelector(".ews-admin-step--warn")?.textContent).toContain("Autodiscover did not answer");
    expect(host.querySelector(".ews-admin-step--fail")).toBeNull();
    expect(host.textContent).toContain("Autodiscover lists none for this account.");
  });

  it("shows a refused request (rate limit) and empties the password", async () => {
    useApi((url) =>
      url.endsWith("/test")
        ? json(429, { detail: { code: "too_many_attempts", message: "Too many tests. Try again in 15 minutes." } })
        : undefined,
    );
    await render();
    await fill("CORP\\s.karimi", "Secret-1");
    await click(button("Run test")!);
    expect(host.querySelector(".ews-admin-test__error")?.textContent).toBe("Too many tests. Try again in 15 minutes.");
    expect(input("ews-test-password").value).toBe("");
  });

  it("keeps the browser from filling in the administrator's own saved sign-in", async () => {
    await render();
    const login = input("ews-test-login");
    const password = input("ews-test-password");
    expect(login.getAttribute("autocomplete")).toBe("off");
    expect(login.name).toBeTruthy();
    expect(login.name).not.toMatch(/user|login|email/i);
    expect(password.type).toBe("password");
    expect(password.getAttribute("autocomplete")).toBe("new-password");
    expect(password.name).not.toMatch(/^password$/i);
  });

  it("asks to save first while the form has unsaved changes", async () => {
    await render();
    await fill("CORP\\s.karimi", "Secret-1");
    expect(button("Run test")!.disabled).toBe(false);
    await type(input("ews-poll"), "7");
    expect(button("Run test")!.disabled).toBe(true);
    expect(host.querySelector(".ews-admin-test")?.textContent).toContain("Save your changes first");
  });

  it("asks for the EWS address to be saved before a test", async () => {
    useApi(undefined, makeSettings({ enabled: false, ews_url: "" }));
    await render();
    await fill("CORP\\s.karimi", "Secret-1");
    expect(button("Run test")!.disabled).toBe(true);
    expect(host.querySelector(".ews-admin-test")?.textContent).toContain("Save the EWS address first");
  });
});
