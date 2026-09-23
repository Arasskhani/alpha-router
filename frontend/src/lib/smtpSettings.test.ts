import { describe, expect, it } from "vitest";

import {
  describeTestResult,
  passwordReuseProblem,
  portAfterSecurityChange,
  portHint,
  protectionLevel,
  sameServer,
  validateSmtpForm,
} from "./smtpSettings";

describe("portAfterSecurityChange", () => {
  it("moves a standard or empty port to the new mode's standard port", () => {
    expect(portAfterSecurityChange("587", "ssl")).toBe("465");
    expect(portAfterSecurityChange("465", "starttls")).toBe("587");
    expect(portAfterSecurityChange("25", "starttls")).toBe("587");
    expect(portAfterSecurityChange("587", "none")).toBe("25");
    expect(portAfterSecurityChange("", "ssl")).toBe("465");
  });

  it("leaves a port the administrator chose alone", () => {
    expect(portAfterSecurityChange("2525", "ssl")).toBe("2525");
    expect(portAfterSecurityChange("8465", "starttls")).toBe("8465");
  });
});

describe("portHint", () => {
  it("names the mismatch that fails in practice", () => {
    expect(portHint("ssl", 587)).toContain("wrong version number");
    expect(portHint("starttls", 465)).toContain("SSL/TLS");
    expect(portHint("none", 587)).toContain("STARTTLS");
    expect(portHint("none", 465)).toContain("SSL/TLS");
    expect(portHint("ssl", 25)).toContain("STARTTLS");
  });

  it("stays quiet for the usual pairs and for ports it knows nothing about", () => {
    expect(portHint("starttls", 587)).toBeNull();
    expect(portHint("starttls", 25)).toBeNull();
    expect(portHint("ssl", 465)).toBeNull();
    expect(portHint("none", 25)).toBeNull();
    expect(portHint("starttls", 2525)).toBeNull();
  });
});

describe("sameServer", () => {
  it("ignores case, surrounding space and trailing dots, like the server", () => {
    expect(sameServer("MAIL.example.com.", " mail.example.com ")).toBe(true);
    expect(sameServer("mail.example.com..", "mail.example.com")).toBe(true);
    expect(sameServer("mail.example.com", "mail.example.net")).toBe(false);
    expect(sameServer(null, "")).toBe(true);
  });
});

describe("passwordReuseProblem", () => {
  const saved = {
    host: "mail.example.com",
    username: "alpha",
    security: "starttls" as const,
    verify_certificate: true,
  };

  it("keeps the password for the same server, username and protection", () => {
    expect(passwordReuseProblem(saved, { ...saved })).toBeNull();
    expect(passwordReuseProblem(saved, { ...saved, host: "MAIL.example.com.", username: " alpha " })).toBeNull();
    expect(passwordReuseProblem(saved, { ...saved, security: "ssl" })).toBeNull();
  });

  it("refuses another server or username", () => {
    expect(passwordReuseProblem(saved, { ...saved, host: "collector.example.net" })).toBe("saved_for_another_server");
    expect(passwordReuseProblem(saved, { ...saved, username: "bob" })).toBe("saved_for_another_server");
  });

  it("refuses a less secure connection and allows a more secure one", () => {
    expect(passwordReuseProblem(saved, { ...saved, security: "none" })).toBe("less_secure_connection");
    expect(passwordReuseProblem(saved, { ...saved, verify_certificate: false })).toBe("less_secure_connection");
    const lenient = { ...saved, verify_certificate: false };
    expect(passwordReuseProblem(lenient, saved)).toBeNull();
    expect(passwordReuseProblem({ ...saved, security: "none" }, lenient)).toBeNull();
  });

  it("ranks the protection the way the server does", () => {
    expect(protectionLevel("none", true)).toBe(0);
    expect(protectionLevel("starttls", false)).toBe(1);
    expect(protectionLevel("ssl", false)).toBe(1);
    expect(protectionLevel("ssl", true)).toBe(2);
  });
});

describe("validateSmtpForm", () => {
  const ok = { host: "mail.example.com", port: "587", from_address: "reports@example.com" };

  it("accepts a plain host, a port in range and an address", () => {
    expect(validateSmtpForm(ok)).toBeNull();
  });

  it("refuses what the server would refuse, with the same words", () => {
    expect(validateSmtpForm({ ...ok, host: "" })).toMatch(/host name/);
    expect(validateSmtpForm({ ...ok, host: "smtp://mail.example.com" })).toMatch(/host name only/);
    expect(validateSmtpForm({ ...ok, host: "mail example.com" })).toMatch(/host name only/);
    expect(validateSmtpForm({ ...ok, port: "0" })).toMatch(/1 to 65535/);
    expect(validateSmtpForm({ ...ok, port: "70000" })).toMatch(/1 to 65535/);
    expect(validateSmtpForm({ ...ok, port: "" })).toMatch(/1 to 65535/);
    expect(validateSmtpForm({ ...ok, from_address: "reports" })).toMatch(/email address/);
    expect(validateSmtpForm({ ...ok, from_address: "reports@[" })).toMatch(/email address/);
    expect(validateSmtpForm({ ...ok, from_address: "reports@example.com;x" })).toMatch(/email address/);
    expect(validateSmtpForm({ ...ok, from_address: "first.last+tag@sub.example.co.uk" })).toBeNull();
  });
});

describe("describeTestResult", () => {
  it("says how it connected and whether the login was tried", () => {
    expect(
      describeTestResult({
        ok: true,
        security: "starttls",
        tls_version: "TLSv1.3",
        certificate_verified: true,
        login_tested: true,
      }),
    ).toBe("Connected with STARTTLS (TLSv1.3). Login succeeded.");
    expect(
      describeTestResult({
        ok: true,
        security: "ssl",
        tls_version: "TLSv1.2",
        certificate_verified: false,
        login_tested: true,
      }),
    ).toBe("Connected with SSL/TLS (TLSv1.2), certificate not verified. Login succeeded.");
    expect(describeTestResult({ ok: true, security: "none", tls_version: null, login_tested: false })).toBe(
      "Connected with no encryption. No login configured.",
    );
  });

  it("explains a login that was not tried", () => {
    expect(
      describeTestResult({
        ok: true,
        security: "starttls",
        login_tested: false,
        login_skipped: "saved_for_another_server",
      }),
    ).toContain("the saved password belongs to another server or username");
    expect(
      describeTestResult({ ok: true, security: "starttls", login_tested: false, login_skipped: "no_password" }),
    ).toContain("there is no password to try");
    expect(
      describeTestResult({
        ok: true,
        security: "none",
        login_tested: false,
        login_skipped: "less_secure_connection",
      }),
    ).toContain("not sent over a less secure connection");
  });

  it("passes the server's explanation of a failure through", () => {
    expect(describeTestResult({ ok: false, error: "mail:587 did not answer with TLS." })).toBe(
      "mail:587 did not answer with TLS.",
    );
    expect(describeTestResult({ ok: false })).toBe("The connection failed.");
  });
});
