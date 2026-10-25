import { describe, expect, it } from "vitest";

import { ago, countCertificates, exampleLogin, fieldForServerMessage, validateExchangeSettings } from "./exchangeAdmin";
import type { ExchangeSettings, ExchangeSettingsResponse } from "./exchangeMail";

const BASE: ExchangeSettings = {
  enabled: true,
  ews_url: "https://mail.corp.example/EWS/Exchange.asmx",
  autodiscover_url: "",
  login_format: "netbios",
  netbios_domain: "",
  upn_suffix: "",
  verify_tls: true,
  ca_bundle_pem: "",
  require_mailbox_match: true,
  allow_full_access: true,
  allow_manual_mailboxes: true,
  allow_drafts: true,
  allow_send: true,
  allow_free_time: true,
  notify_enabled: true,
  poll_minutes: 5,
  detection: "rules",
  detection_model: "",
  search_limit: 25,
  body_chars: 8000,
  timeout_s: 30,
  max_mailboxes: 10,
  action_retention_days: 30,
};

const FIELDS = Object.keys(BASE) as (keyof ExchangeSettings)[];

describe("validateExchangeSettings", () => {
  it("accepts the defaults with an address", () => {
    expect(validateExchangeSettings(BASE)).toEqual({});
  });

  it("keeps every number within the server's bounds", () => {
    const errors = validateExchangeSettings({ ...BASE, poll_minutes: 1, body_chars: 30001, timeout_s: Number.NaN, max_mailboxes: 2.5 });
    expect(errors).toEqual({
      poll_minutes: "Enter a whole number from 2 to 60.",
      body_chars: "Enter a whole number from 1000 to 30000.",
      timeout_s: "Enter a whole number from 5 to 120.",
      max_mailboxes: "Enter a whole number from 1 to 50.",
    });
  });

  it("asks for https addresses, and for one before turning it on", () => {
    expect(validateExchangeSettings({ ...BASE, ews_url: "http://mail.corp.example" }).ews_url).toContain("https");
    expect(validateExchangeSettings({ ...BASE, ews_url: "https://user:pw@mail.corp.example" }).ews_url).toContain("https");
    expect(validateExchangeSettings({ ...BASE, ews_url: "" }).ews_url).toBe(
      "Give the EWS address before turning Exchange EWS on.",
    );
    expect(validateExchangeSettings({ ...BASE, enabled: false, ews_url: "" })).toEqual({});
    expect(validateExchangeSettings({ ...BASE, autodiscover_url: "mail.corp.example" }).autodiscover_url).toBe(
      "Enter an https address, or leave it blank.",
    );
  });

  it("checks the domain, the suffix, the certificates and the model", () => {
    const errors = validateExchangeSettings({
      ...BASE,
      netbios_domain: "corp domain",
      upn_suffix: "corp",
      ca_bundle_pem: "not a certificate",
      detection: "model",
    });
    expect(Object.keys(errors).sort()).toEqual(["ca_bundle_pem", "detection_model", "netbios_domain", "upn_suffix"]);
    expect(validateExchangeSettings({ ...BASE, netbios_domain: "CORP", upn_suffix: "@corp.example" })).toEqual({});
  });
});

describe("fieldForServerMessage", () => {
  it("reads the setting's key, or the words the server uses for it", () => {
    expect(fieldForServerMessage("poll_minutes must be a whole number from 2 to 60.", FIELDS)).toBe("poll_minutes");
    expect(fieldForServerMessage("detection must be one of rules, model.", FIELDS)).toBe("detection");
    expect(fieldForServerMessage("The EWS address must be an https address, such as …", FIELDS)).toBe("ews_url");
    expect(fieldForServerMessage("Give the EWS address before turning Exchange EWS on.", FIELDS)).toBe("ews_url");
    expect(fieldForServerMessage("The Autodiscover address must be an https address, or blank.", FIELDS)).toBe(
      "autodiscover_url",
    );
    expect(fieldForServerMessage("The NetBIOS domain is a short name such as CORP", FIELDS)).toBe("netbios_domain");
    expect(fieldForServerMessage("The UPN suffix is a domain such as corp.example.", FIELDS)).toBe("upn_suffix");
    expect(fieldForServerMessage("One of the CA certificates could not be read.", FIELDS)).toBe("ca_bundle_pem");
    expect(fieldForServerMessage("Choose the model that picks emails needing action, or use the rules.", FIELDS)).toBe(
      "detection_model",
    );
    expect(fieldForServerMessage("Send the settings as an object.", FIELDS)).toBeNull();
  });
});

describe("exampleLogin", () => {
  const saved: Pick<ExchangeSettingsResponse, "settings" | "directory" | "example_login"> = {
    settings: BASE,
    directory: { netbios_domain: "CORP", dns_domain: "corp.example", available: true },
    example_login: "CORP\\m.arasskhani",
  };

  it("is the server's example while the login settings are the saved ones", () => {
    expect(exampleLogin(BASE, saved)).toEqual({ login: "CORP\\m.arasskhani", saved: true });
  });

  it("is rebuilt from the same user name for a changed format or domain", () => {
    expect(exampleLogin({ ...BASE, netbios_domain: "hq" }, saved)).toEqual({ login: "HQ\\m.arasskhani", saved: false });
    expect(exampleLogin({ ...BASE, login_format: "upn" }, saved)).toEqual({
      login: "m.arasskhani@corp.example",
      saved: false,
    });
    expect(exampleLogin({ ...BASE, login_format: "upn", upn_suffix: "@Corp.Local" }, saved).login).toBe(
      "m.arasskhani@corp.local",
    );
    expect(exampleLogin({ ...BASE, login_format: "email" }, saved).login).toBeNull();
  });

  it("is none when no domain is known", () => {
    const bare = { ...saved, directory: { netbios_domain: "", dns_domain: "", available: false }, example_login: "" };
    expect(exampleLogin(BASE, bare)).toEqual({ login: null, saved: true });
    expect(exampleLogin({ ...BASE, login_format: "upn" }, bare)).toEqual({ login: null, saved: false });
  });
});

describe("small helpers", () => {
  it("counts PEM certificates", () => {
    const pem = "-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----";
    expect(countCertificates(`${pem}\n${pem}`)).toBe(2);
    expect(countCertificates("hello")).toBe(0);
  });

  it("says how long ago", () => {
    const now = new Date("2026-10-25T12:00:00Z");
    expect(ago(null, now)).toBe("Never");
    expect(ago("2026-10-25T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-10-25T11:52:00Z", now)).toBe("8 min ago");
    expect(ago("2026-10-25T09:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-10-24T10:00:00Z", now)).toBe("yesterday");
    expect(ago("2026-10-21T12:00:00Z", now)).toBe("4 days ago");
    expect(ago("2026-09-01T12:00:00Z", now)).toContain("2026");
  });
});
