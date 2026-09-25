/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { challengeFor, createState, createVerifier } from "./pkce";

describe("PKCE", () => {
  it("matches RFC 7636, appendix B", async () => {
    expect(await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("makes verifiers the server accepts, and never the same one twice", () => {
    const a = createVerifier();
    const b = createVerifier();
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(a).not.toBe(b);
  });

  it("makes states the server accepts", () => {
    const state = createState();
    // The server wants 16-128 characters of [A-Za-z0-9_-].
    expect(state).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(createState()).not.toBe(state);
  });

  it("gives a 43-character challenge", async () => {
    expect(await challengeFor(createVerifier())).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });
});
