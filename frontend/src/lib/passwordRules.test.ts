import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_PASSWORD_POLICY, loadPasswordPolicy, resetPasswordPolicyCache, unmetPasswordRules } from "./passwordRules";

afterEach(() => resetPasswordPolicyCache());

describe("unmetPasswordRules", () => {
  it("names every rule a short simple password misses, in order", () => {
    expect(unmetPasswordRules("abc")).toEqual(["length", "upper", "digit", "symbol"]);
  });

  it("is satisfied by a long password with every kind of character", () => {
    expect(unmetPasswordRules("aStrong-1Pass!")).toEqual([]);
  });

  it("does not count a space as a symbol", () => {
    expect(unmetPasswordRules("Has Spaces 123")).toContain("symbol");
  });

  it("refuses the username or the name part of the email, as the server does", () => {
    expect(unmetPasswordRules("Sara-Pass-123!", { username: "sara" })).toEqual(["personal"]);
    expect(unmetPasswordRules("Xmajid!2026Q", { email: "Majid@example.com" })).toEqual(["personal"]);
    expect(unmetPasswordRules("Abc-def-123!", { username: "ab" })).toEqual([]);
  });

  it("tests digits, case and the common list as the server does", () => {
    // A decimal digit (Nd), as Python's isdecimal(): a superscript two is not one, an Arabic-Indic three is.
    expect(unmetPasswordRules("Abcdefg!²")).toContain("digit");
    expect(unmetPasswordRules("Abcdefg!٣")).not.toContain("digit");
    // Lowercase, as Python's lower(): "ß" is not "ss".
    expect(unmetPasswordRules("Straße-Kp9", { username: "strasse" })).toEqual([]);
    expect(unmetPasswordRules("Alpha-Router123", { common: ["alpha-router123"] })).toEqual(["common"]);
    expect(unmetPasswordRules("Alpha-Router123")).toEqual([]);
  });

  it("follows the server's minimum length", () => {
    expect(unmetPasswordRules("aStrong-1Pass!", { minLength: 20 })).toEqual(["length"]);
  });
});

describe("loadPasswordPolicy", () => {
  it("reads the server's policy once", async () => {
    const policy = { ...DEFAULT_PASSWORD_POLICY, min_length: 12 };
    const fetcher = vi.fn(async () => new Response(JSON.stringify(policy)));
    expect((await loadPasswordPolicy(fetcher)).min_length).toBe(12);
    await loadPasswordPolicy(fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("falls back to the defaults when it cannot", async () => {
    const fetcher = vi.fn(async () => {
      throw new Error("offline");
    });
    expect(await loadPasswordPolicy(fetcher)).toEqual(DEFAULT_PASSWORD_POLICY);
  });
});
