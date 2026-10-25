/**
 * @vitest-environment happy-dom
 *
 * Connections in the profile menu: there, above Settings, only for an account
 * that may connect an Exchange mailbox (`features.connections === true`), and
 * pointing at the Connections page of the person's own panel.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  role: "user",
  session: null as Record<string, unknown> | null,
}));

vi.mock("../api", () => ({ api: () => new Promise(() => {}) }));
vi.mock("../hooks/useCachedSession", () => ({ useCachedSession: () => state.session }));
vi.mock("../lib/session", () => ({
  getSessionUser: () => ({ username: "sara", display_name: null, role: state.role, loginAt: Date.now() }),
  formatSessionDuration: () => "1 min",
  getMyActivityPath: () => "/app/my-activity",
  logout: () => {},
}));
vi.mock("../lib/chatStorage", () => ({ clearStoredImageGenerationForCurrentUser: () => Promise.resolve() }));
vi.mock("./SettingsModal", () => ({ default: () => null }));
vi.mock("./ThemePicker", () => ({ default: () => null }));
vi.mock("../lib/pwa/installPrompt", () => ({
  useInstallState: () => "unavailable",
  promptInstall: vi.fn(),
  onAppInstalled: () => () => {},
}));
vi.mock("../lib/pwa/installSuggestion", () => ({ markInstallDone: vi.fn() }));

import UserProfile from "./UserProfile";

let host: HTMLDivElement;
let root: Root;

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname}</output>;
}

async function openMenu() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/app/chat"]}>
        <UserProfile theme="light" onThemeChange={() => {}} />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await act(async () => host.querySelector<HTMLButtonElement>(".user-profile-trigger")!.click());
}

const items = () => [...host.querySelectorAll<HTMLElement>('[role="menuitem"]')];
const connections = () => items().find((el) => el.textContent?.trim() === "Connections") ?? null;

beforeEach(() => {
  state.role = "user";
  state.session = { role: "user", features: { connections: true, exchange_mail: false } };
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

describe("Connections in the profile menu", () => {
  it("sits just above Settings, with the plug icon", async () => {
    await openMenu();
    const item = connections();
    expect(item).toBeTruthy();
    const labels = items().map((el) => el.textContent?.trim());
    expect(labels.indexOf("Connections")).toBe(labels.indexOf("Settings") - 1);
    expect(item!.querySelector(".user-profile-menu-icon svg")).toBeTruthy();
  });

  it("opens the user panel's page and closes the menu", async () => {
    await openMenu();
    expect(connections()!.getAttribute("href")).toBe("/app/connections");
    await act(async () => connections()!.click());
    expect(host.querySelector('[data-testid="where"]')?.textContent).toBe("/app/connections");
    expect(host.querySelector('[role="menu"]')).toBeNull();
  });

  it("opens the admin panel's page for an admin-panel role", async () => {
    state.role = "full_administrator";
    await openMenu();
    expect(connections()!.getAttribute("href")).toBe("/admin/my-connections");
  });

  it("is not there when the account may not connect a mailbox, or the server does not say", async () => {
    for (const session of [
      { role: "user", features: { connections: false, exchange_mail: false } },
      { role: "user", features: {} },
      { role: "user" },
      null,
    ]) {
      state.session = session;
      await openMenu();
      expect(connections()).toBeNull();
      expect(items().some((el) => el.textContent?.trim() === "Settings")).toBe(true);
      await act(async () => host.querySelector<HTMLButtonElement>(".user-profile-trigger")!.click());
    }
  });
});
