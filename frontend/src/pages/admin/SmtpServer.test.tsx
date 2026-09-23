/**
 * @vitest-environment happy-dom
 *
 * The SMTP Server page: labelled fields, an explicit choice of connection
 * security instead of the old "Use TLS" switch (which meant the kind of TLS
 * port 587 does not speak), the self-signed exception, a password that stays
 * with its server, and test results a person can act on.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { api } from "../../api";
import SmtpServer from "./SmtpServer";

const SAVED = {
  host: "mail.example.com",
  port: 587,
  username: "alpha",
  password: "********",
  from_address: "reports@example.com",
  security: "starttls",
  verify_certificate: true,
};

type Handler = (init?: RequestInit) => unknown;

function answer({
  saved = SAVED as unknown,
  put,
  test,
  mail,
}: { saved?: unknown; put?: Handler; test?: Handler; mail?: Handler } = {}) {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/api/admin/smtp" && (!init || !init.method)) return saved;
    if (path === "/api/admin/smtp" && init?.method === "PUT") return put ? put(init) : { ok: true };
    if (path === "/api/admin/smtp/test") return test ? test(init) : { ok: true, security: "starttls" };
    if (path === "/api/admin/smtp/test-email") return mail ? mail(init) : { ok: true, to: "admin@example.com" };
    throw new Error(`unexpected ${path}`);
  });
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  readOnly.value = false;
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
    root.render(<SmtpServer />);
  });
}

const field = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as T;
const button = (label: string) =>
  [...document.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label);

function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function choose(el: HTMLSelectElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function click(el: Element | undefined | null) {
  if (!el) throw new Error("nothing to click");
  return act(async () => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

async function submit() {
  const form = document.querySelector("form")!;
  await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}

function sent(path: string, method: string) {
  return vi
    .mocked(api)
    .mock.calls.filter((c) => c[0] === path && (c[1] as RequestInit | undefined)?.method === method)
    .map((c) => JSON.parse(String((c[1] as RequestInit).body)));
}

const text = () => document.body.textContent || "";

describe("the SMTP Server page", () => {
  it("shows the saved settings in labelled fields, and never the password", async () => {
    answer();
    await render();
    expect(document.querySelector('label[for="smtp-host"]')?.textContent).toBe("Server");
    expect(field("smtp-host").value).toBe("mail.example.com");
    expect(field<HTMLSelectElement>("smtp-security").value).toBe("starttls");
    expect(field("smtp-port").value).toBe("587");
    expect(field("smtp-username").value).toBe("alpha");
    expect(field("smtp-password").value).toBe("");
    expect(field("smtp-password").placeholder).toBe("Saved — leave blank to keep it");
    expect(field("smtp-from").value).toBe("reports@example.com");
    expect(field("smtp-self-signed").checked).toBe(false);
  });

  it("keeps the browser from filling in the administrator's own password", async () => {
    answer();
    await render();
    expect(field("smtp-password").getAttribute("autocomplete")).toBe("new-password");
    expect(field("smtp-username").getAttribute("autocomplete")).toBe("off");
  });

  it("moves a standard port with the security mode and leaves a chosen one alone", async () => {
    answer();
    await render();
    await choose(field<HTMLSelectElement>("smtp-security"), "ssl");
    expect(field("smtp-port").value).toBe("465");
    await choose(field<HTMLSelectElement>("smtp-security"), "starttls");
    expect(field("smtp-port").value).toBe("587");

    await type(field("smtp-port"), "2525");
    await choose(field<HTMLSelectElement>("smtp-security"), "ssl");
    expect(field("smtp-port").value).toBe("2525");
  });

  it("warns about the pairing that produced “wrong version number”", async () => {
    answer({ saved: { ...SAVED, security: "ssl", port: 587 } });
    await render();
    expect(document.querySelector(".smtp-hint--warn")?.textContent).toContain("Port 587 normally uses STARTTLS");
  });

  it("warns loudly about no encryption and has no certificate to excuse", async () => {
    answer();
    await render();
    await choose(field<HTMLSelectElement>("smtp-security"), "none");
    expect(text()).toContain("No encryption.");
    expect(field("smtp-self-signed").disabled).toBe(true);
  });

  it("allows a self-signed certificate only with a warning, and says so to the server", async () => {
    answer();
    await render();
    expect(text()).not.toContain("Certificate not checked.");
    await click(field("smtp-self-signed"));
    expect(text()).toContain("Certificate not checked.");
    // The saved password is not sent past an unchecked certificate until it is typed again.
    expect(button("Save")?.disabled).toBe(true);
    expect(document.getElementById("smtp-password-hint")?.textContent).toContain("less secure connection");
    await type(field("smtp-password"), "s3cret");
    await submit();
    expect(sent("/api/admin/smtp", "PUT")[0]).toMatchObject({ verify_certificate: false, password: "s3cret" });
  });

  it("asks for the password again before dropping encryption", async () => {
    answer();
    await render();
    await choose(field<HTMLSelectElement>("smtp-security"), "none");
    expect(button("Save")?.disabled).toBe(true);
    expect(document.getElementById("smtp-password-hint")?.textContent).toContain("less secure connection");
  });

  it("keeps the saved password for a more secure connection", async () => {
    answer({ saved: { ...SAVED, verify_certificate: false } });
    await render();
    expect(field("smtp-self-signed").checked).toBe(true);
    await click(field("smtp-self-signed"));
    expect(button("Save")?.disabled).toBe(false);
    await submit();
    expect(sent("/api/admin/smtp", "PUT")[0]).toMatchObject({ verify_certificate: true, password: null });
  });

  it("saves the explicit mode and keeps the saved password when the field is left empty", async () => {
    answer();
    await render();
    await type(field("smtp-from"), "alerts@example.com");
    await submit();
    expect(sent("/api/admin/smtp", "PUT")).toEqual([
      {
        host: "mail.example.com",
        port: 587,
        security: "starttls",
        verify_certificate: true,
        username: "alpha",
        password: null,
        from_address: "alerts@example.com",
      },
    ]);
    expect(document.querySelector(".smtp-result")?.textContent).toBe("SMTP settings saved.");
  });

  it("shows why a save was refused", async () => {
    answer({
      put: () => {
        throw new Error("Enter the password again: a saved password is only ever sent to the server it was saved for.");
      },
    });
    await render();
    await submit();
    expect(document.querySelector('.smtp-result[role="alert"]')?.textContent).toContain("Enter the password again");
  });

  it("asks for the password again before saving a new host", async () => {
    answer();
    await render();
    await type(field("smtp-host"), "smtp.example.net");
    expect(button("Save")?.disabled).toBe(true);
    expect(document.getElementById("smtp-password-hint")?.textContent).toContain(
      "only used with the server and username it was saved for",
    );
    // Not even a submit that bypasses the button (Enter in a field) goes out.
    await submit();
    expect(sent("/api/admin/smtp", "PUT")).toEqual([]);
    expect(document.querySelector('.smtp-result[role="alert"]')?.textContent).toContain("Enter the password again");

    await type(field("smtp-password"), "n3w");
    expect(button("Save")?.disabled).toBe(false);
    await submit();
    expect(sent("/api/admin/smtp", "PUT")[0]).toMatchObject({ host: "smtp.example.net", password: "n3w" });
  });

  it("does not ask when the host is the same server spelled differently", async () => {
    answer();
    await render();
    await type(field("smtp-host"), "MAIL.example.com..");
    expect(button("Save")?.disabled).toBe(false);
  });

  it("asks for the password again for another username", async () => {
    answer();
    await render();
    await type(field("smtp-username"), "bob");
    expect(button("Save")?.disabled).toBe(true);
    expect(document.getElementById("smtp-password-hint")?.textContent).toContain("server and username");
  });

  it("does not take the mask typed into the password field for a password", async () => {
    answer();
    await render();
    await type(field("smtp-host"), "smtp.example.net");
    await type(field("smtp-password"), "********");
    expect(button("Save")?.disabled).toBe(true);
  });

  it("refuses a URL for a host name without asking the server", async () => {
    answer();
    await render();
    await type(field("smtp-host"), "smtp://mail.example.com");
    await type(field("smtp-password"), "x");
    await submit();
    expect(sent("/api/admin/smtp", "PUT")).toEqual([]);
    expect(document.querySelector('.smtp-result[role="alert"]')?.textContent).toContain("host name only");
  });

  it("reports a successful test in words", async () => {
    answer({
      test: () => ({
        ok: true,
        security: "starttls",
        tls_version: "TLSv1.3",
        certificate_verified: true,
        login_tested: true,
        login_skipped: null,
      }),
    });
    await render();
    await click(button("Test connection"));
    expect(sent("/api/admin/smtp/test", "POST")[0]).toMatchObject({ security: "starttls", password: null });
    expect(document.querySelector('.smtp-result[role="status"]')?.textContent).toBe(
      "Connected with STARTTLS (TLSv1.3). Login succeeded.",
    );
  });

  it("shows the server's explanation when the test fails", async () => {
    answer({
      test: () => ({
        ok: false,
        error: "mail.example.com:587 did not answer with TLS. Port 587 most likely expects STARTTLS: choose STARTTLS.",
      }),
    });
    await render();
    await click(button("Test connection"));
    expect(document.querySelector('.smtp-result[role="alert"]')?.textContent).toContain("choose STARTTLS");
  });

  it("starts empty with STARTTLS on 587 when nothing is configured", async () => {
    answer({ saved: null });
    await render();
    expect(field("smtp-host").value).toBe("");
    expect(field<HTMLSelectElement>("smtp-security").value).toBe("starttls");
    expect(field("smtp-port").value).toBe("587");
    expect(field("smtp-password").placeholder).toBe("");
  });

  it("lets a read-only administrator look but not save or test", async () => {
    readOnly.value = true;
    answer();
    await render();
    expect(button("Save")?.disabled).toBe(true);
    expect(button("Test connection")?.disabled).toBe(true);
    expect(button("Send test email to me")?.disabled).toBe(true);
    expect(field("smtp-self-signed").disabled).toBe(true);
  });
});

describe("Send test email to me", () => {
  const mailCalls = () => vi.mocked(api).mock.calls.filter((c) => c[0] === "/api/admin/smtp/test-email");

  it("sends with the saved settings and says which address the server accepted", async () => {
    answer();
    await render();
    expect(document.getElementById("smtp-mail-hint")).toBeNull();
    await click(button("Send test email to me"));
    expect(mailCalls()).toHaveLength(1);
    // Nothing from the form: the server sends with what is saved, to the administrator's own address.
    expect((mailCalls()[0][1] as RequestInit).body).toBeUndefined();
    expect(document.querySelector('.smtp-mail-result[role="status"]')?.textContent).toBe(
      "The mail server accepted a test email for admin@example.com. If it does not arrive, look in the spam folder.",
    );
  });

  it("waits for unsaved changes to be saved first", async () => {
    answer();
    await render();
    await type(field("smtp-from"), "alerts@example.com");
    expect(button("Send test email to me")?.disabled).toBe(true);
    expect(document.getElementById("smtp-mail-hint")?.textContent).toBe(
      "Save your changes first: the test email is sent with the saved settings.",
    );
    // Typing the password counts as a change too.
    await type(field("smtp-from"), "reports@example.com");
    expect(button("Send test email to me")?.disabled).toBe(false);
    await type(field("smtp-password"), "n3w");
    expect(button("Send test email to me")?.disabled).toBe(true);

    await submit();
    expect(button("Send test email to me")?.disabled).toBe(false);
    expect(document.getElementById("smtp-mail-hint")).toBeNull();
  });

  it("cannot send before anything is saved", async () => {
    answer({ saved: null });
    await render();
    expect(button("Send test email to me")?.disabled).toBe(true);
    expect(document.getElementById("smtp-mail-hint")?.textContent).toContain("Save the settings first");
  });

  it("shows the server's explanation when the email could not be sent", async () => {
    answer({ mail: () => ({ ok: false, error: "mail.example.com rejected the username or password (535)." }) });
    await render();
    await click(button("Send test email to me"));
    expect(document.querySelector('.smtp-mail-result[role="alert"]')?.textContent).toBe(
      "mail.example.com rejected the username or password (535).",
    );
  });

  it("shows why the server refused to try", async () => {
    answer({
      mail: () => {
        throw new Error("Your account has no email address to send the test to.");
      },
    });
    await render();
    await click(button("Send test email to me"));
    expect(document.querySelector('.smtp-mail-result[role="alert"]')?.textContent).toBe(
      "Your account has no email address to send the test to.",
    );
  });
});
