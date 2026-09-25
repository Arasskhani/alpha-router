/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  api: vi.fn(),
  bootstrapSession: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../lib/themeCache", () => ({ applyThemeToDocument: () => {} }));

import { api, bootstrapSession } from "../api";
import { STORAGE_KEYS } from "../lib/brand";
import ExtensionConnect, { navigation, parseConnectRequest } from "./ExtensionConnect";

const ID = "abcdefghijklmnopabcdefghijklmnop";
const REDIRECT = `chrome-extension://${ID}/connected.html`;
const CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
const STATE = "state-0123456789abcdef";

function search(over: Record<string, string> = {}): string {
  const params = new URLSearchParams({
    redirect_uri: REDIRECT,
    code_challenge: CHALLENGE,
    code_challenge_method: "S256",
    state: STATE,
    ...over,
  });
  return `?${params.toString()}`;
}

const SESSION = { username: "majid", display_name: "Majid A.", role: "user", is_active: true, auth_provider: "local" };

let host: HTMLDivElement;
let root: Root;
let go: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(bootstrapSession).mockReset();
  go = vi.spyOn(navigation, "go").mockImplementation(() => {});
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

async function render(query = search()) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[`/extension/connect${query}`]}>
        <Routes>
          <Route path="/extension/connect" element={<ExtensionConnect />} />
          <Route path="/login" element={<p>LOGIN PAGE</p>} />
        </Routes>
      </MemoryRouter>,
    );
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label);
  if (!found) throw new Error(`no ${label} button`);
  return found as HTMLButtonElement;
}

function signedIn(info: Record<string, unknown> = { permitted: true, extension_id: ID }) {
  vi.mocked(bootstrapSession).mockResolvedValue(SESSION as never);
  vi.mocked(api).mockResolvedValueOnce(info as never);
}

describe("reading the request", () => {
  it("takes a well-formed request", () => {
    expect(parseConnectRequest(search())).toEqual({
      redirectUri: REDIRECT,
      extensionId: ID,
      codeChallenge: CHALLENGE,
      state: STATE,
    });
    expect(parseConnectRequest(search({ redirect_uri: `extension://${ID}/connected.html` }))?.extensionId).toBe(ID);
  });

  it.each<Record<string, string>>([
    { redirect_uri: "https://evil.example/connected.html" },
    { redirect_uri: `chrome-extension://${ID}/sidepanel.html` },
    { redirect_uri: `chrome-extension://${ID.toUpperCase()}/connected.html` },
    { redirect_uri: `chrome-extension://${ID}/connected.html?x=1` },
    { code_challenge_method: "plain" },
    { code_challenge: "short" },
    { state: "short" },
    { state: "has spaces in the state!" },
  ])("refuses %o", (over) => {
    expect(parseConnectRequest(search(over))).toBeNull();
  });
});

describe("the connect page", () => {
  it("asks, then sends the tab back to the extension with the code", async () => {
    signedIn();
    await render();
    expect(host.textContent).toContain("Connect this browser?");
    expect(host.textContent).toContain("Majid A.");
    vi.mocked(api).mockResolvedValueOnce({ redirect_to: `${REDIRECT}?code=abc&state=${STATE}` } as never);
    await act(async () => button("Connect").click());
    expect(api).toHaveBeenLastCalledWith("/api/extension/authorize", {
      method: "POST",
      body: JSON.stringify({
        redirect_uri: REDIRECT,
        code_challenge: CHALLENGE,
        code_challenge_method: "S256",
        state: STATE,
        deny: false,
      }),
    });
    expect(go).toHaveBeenCalledWith(`${REDIRECT}?code=abc&state=${STATE}`);
    expect(host.textContent).toContain("returning to the extension");
  });

  it("Cancel sends the refusal back", async () => {
    signedIn();
    await render();
    vi.mocked(api).mockResolvedValueOnce({ redirect_to: `${REDIRECT}?error=access_denied&state=${STATE}` } as never);
    await act(async () => button("Cancel").click());
    const body = JSON.parse(String((vi.mocked(api).mock.calls.at(-1)?.[1] as RequestInit).body));
    expect(body.deny).toBe(true);
    expect(go).toHaveBeenCalledWith(`${REDIRECT}?error=access_denied&state=${STATE}`);
  });

  it("sends a signed-out user to sign in, and remembers to come back", async () => {
    vi.mocked(bootstrapSession).mockRejectedValue(new Error("Not authenticated"));
    await render();
    expect(host.textContent).toContain("LOGIN PAGE");
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEYS.afterLogin) ?? "{}");
    expect(stored.target).toBe(`/extension/connect${search()}`);
  });

  it("forgets the page to resume once signed in", async () => {
    sessionStorage.setItem(STORAGE_KEYS.afterLogin, JSON.stringify({ target: `/extension/connect${search()}`, at: Date.now() }));
    signedIn();
    await render();
    expect(sessionStorage.getItem(STORAGE_KEYS.afterLogin)).toBeNull();
  });

  it("refuses a broken link without asking the server anything", async () => {
    await render(search({ code_challenge: "tampered" }));
    expect(host.textContent).toContain("This link cannot connect a browser");
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(bootstrapSession).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(STORAGE_KEYS.afterLogin)).toBeNull();
  });

  it("says so when the admin has not enabled the extension for the user", async () => {
    signedIn({ permitted: false, extension_id: ID });
    await render();
    expect(host.textContent).toContain("not enabled for your account");
    expect(host.querySelectorAll("button")).toHaveLength(0);
  });

  it("says so when the extension belongs to another server", async () => {
    signedIn({ permitted: true, extension_id: "ponmlkjihgfedcbaponmlkjihgfedcba" });
    await render();
    expect(host.textContent).toContain("belongs to another server");
    expect(host.querySelectorAll("button")).toHaveLength(0);
  });

  it("says so for a disabled account", async () => {
    vi.mocked(bootstrapSession).mockResolvedValue({ ...SESSION, is_active: false } as never);
    await render();
    expect(host.textContent).toContain("Your account is disabled");
    expect(api).not.toHaveBeenCalled();
  });

  it("still asks when the extension details cannot be read, leaving the decision to the server", async () => {
    vi.mocked(bootstrapSession).mockResolvedValue(SESSION as never);
    vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
    await render();
    expect(host.textContent).toContain("Connect this browser?");
  });

  it("shows the server's refusal and lets the user try again", async () => {
    signedIn();
    await render();
    vi.mocked(api).mockRejectedValueOnce(new Error("That is not this server's browser extension."));
    await act(async () => button("Connect").click());
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("not this server's browser extension");
    expect(button("Connect").disabled).toBe(false);
    expect(go).not.toHaveBeenCalled();
  });

  it("never follows an address that is not the extension's own page", async () => {
    signedIn();
    await render();
    vi.mocked(api).mockResolvedValueOnce({ redirect_to: "https://evil.example/?code=abc" } as never);
    await act(async () => button("Connect").click());
    expect(go).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("unexpected address");
  });
});
