/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
  bootstrapSession: vi.fn(),
}));
vi.mock("../lib/themeCache", () => ({ applyThemeToDocument: () => {} }));
vi.mock("../lib/session", () => ({ markLoggedIn: () => {} }));

import { authFetch, bootstrapSession } from "../api";
import { STORAGE_KEYS } from "../lib/brand";
import Login from "./Login";

const CONNECT = "/extension/connect?redirect_uri=x&state=y";

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(authFetch).mockReset();
  vi.mocked(bootstrapSession).mockReset();
  vi.mocked(authFetch).mockImplementation(async (path: string) => {
    if (path === "/api/auth/methods") return new Response(JSON.stringify({ ldap: false, saml: false, oidc: false }));
    return new Response(JSON.stringify({ ok: true }));
  });
  vi.mocked(bootstrapSession).mockResolvedValue({ username: "u", role: "user", is_active: true, auth_provider: "local" } as never);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  sessionStorage.clear();
});

async function signIn(): Promise<string> {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  const form = host.querySelector("form") as HTMLFormElement;
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  return host.querySelector('[data-testid="where"]')?.textContent ?? "";
}

describe("after signing in", () => {
  it("goes back to the extension's connect page that sent the user here", async () => {
    sessionStorage.setItem(STORAGE_KEYS.afterLogin, JSON.stringify({ target: CONNECT, at: Date.now() }));
    expect(await signIn()).toBe(CONNECT);
    expect(sessionStorage.getItem(STORAGE_KEYS.afterLogin)).toBeNull();
  });

  it("goes home when nothing asked to be resumed", async () => {
    expect(await signIn()).toBe("/app/chat");
  });

  it("goes home when storage names anywhere else", async () => {
    sessionStorage.setItem(STORAGE_KEYS.afterLogin, JSON.stringify({ target: "/admin/users", at: Date.now() }));
    expect(await signIn()).toBe("/app/chat");
  });
});
