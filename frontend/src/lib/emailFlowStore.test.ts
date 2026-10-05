/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it } from "vitest";

import { STORAGE_KEYS } from "./brand";
import { clearEmailFlow, loadEmailFlow, saveEmailFlow } from "./emailFlowStore";

const STARTED = { token: "tok", email: "a@example.com", expires_in: 600, resend_in: 60, code_length: 6 };

afterEach(() => sessionStorage.clear());

describe("the email flow in progress", () => {
  it("comes back after a reload, until the code expires", () => {
    saveEmailFlow({ flow: "signup", step: "code", started: STARTED }, 1_000_000);
    expect(loadEmailFlow(1_000_000 + 599_000)?.started.token).toBe("tok");
    expect(loadEmailFlow(1_000_000 + 601_000)).toBeNull();
    expect(sessionStorage.getItem(STORAGE_KEYS.emailFlow)).toBeNull();
  });

  it("keeps the last step for 30 minutes after the code", () => {
    saveEmailFlow({ flow: "reset", step: "password", started: STARTED, username: "me" }, 0);
    expect(loadEmailFlow(29 * 60_000)?.username).toBe("me");
    expect(loadEmailFlow(31 * 60_000)).toBeNull();
  });

  it("ignores what it did not write", () => {
    sessionStorage.setItem(STORAGE_KEYS.emailFlow, JSON.stringify({ flow: "signup", step: "code" }));
    expect(loadEmailFlow()).toBeNull();
    sessionStorage.setItem(STORAGE_KEYS.emailFlow, "{not json");
    expect(loadEmailFlow()).toBeNull();
  });

  it("is gone once cleared", () => {
    saveEmailFlow({ flow: "signup", step: "code", started: STARTED });
    clearEmailFlow();
    expect(loadEmailFlow()).toBeNull();
  });
});
