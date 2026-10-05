/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  authFetch: vi.fn(async () => new Response("{}", { status: 500 })),
}));

import { resetPasswordPolicyCache } from "../../lib/passwordRules";
import PasswordRules from "./PasswordRules";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  resetPasswordPolicyCache();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(password: string, extra: { username?: string } = {}) {
  await act(async () => {
    root.render(<PasswordRules password={password} {...extra} />);
  });
}

function met(): string[] {
  return [...host.querySelectorAll(".password-rules__rule--met")].map((li) => li.textContent ?? "");
}

describe("PasswordRules", () => {
  it("ticks nothing before anything is typed", async () => {
    await render("");
    expect(host.querySelectorAll("li")).toHaveLength(6);
    expect(met()).toEqual([]);
  });

  it("ticks each rule the password meets", async () => {
    await render("abcdefgh1");
    const ticked = met().join(" | ");
    expect(ticked).toContain("At least 8 characters");
    expect(ticked).toContain("A lowercase letter");
    expect(ticked).toContain("A digit");
    expect(ticked).not.toContain("An uppercase letter");
    expect(ticked).not.toContain("A symbol");
  });

  it("does not tick the personal rule when the username is in the password", async () => {
    await render("Sara-Pass-123!", { username: "sara" });
    expect(met().join(" | ")).not.toContain("Not your username");
  });
});
