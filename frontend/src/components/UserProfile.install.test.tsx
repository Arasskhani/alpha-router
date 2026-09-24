/**
 * @vitest-environment happy-dom
 *
 * "Install app" in the profile menu: there whenever this device can install
 * the app, on phones and desktops alike, and gone otherwise.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const install = vi.hoisted(() => ({ state: "can-prompt" as string, outcome: "accepted" as string }));

vi.mock("../api", () => ({ api: () => new Promise(() => {}) }));
vi.mock("../lib/session", () => ({
  getSessionUser: () => ({ username: "sara", display_name: null, role: "user", loginAt: Date.now() }),
  formatSessionDuration: () => "1 min",
  getMyActivityPath: () => "/app/my-activity",
  logout: () => {},
}));
vi.mock("../lib/chatStorage", () => ({ clearStoredImageGenerationForCurrentUser: () => Promise.resolve() }));
vi.mock("./SettingsModal", () => ({ default: () => null }));
vi.mock("./ThemePicker", () => ({ default: () => null }));
vi.mock("../lib/pwa/installPrompt", () => ({
  useInstallState: () => install.state,
  promptInstall: vi.fn(() => Promise.resolve(install.outcome)),
  onAppInstalled: () => () => {},
}));
vi.mock("../lib/pwa/installSuggestion", () => ({ markInstallDone: vi.fn() }));

import { promptInstall } from "../lib/pwa/installPrompt";
import { markInstallDone } from "../lib/pwa/installSuggestion";
import UserProfile from "./UserProfile";

let host: HTMLDivElement;
let root: Root;

async function openMenu() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <UserProfile theme="light" onThemeChange={() => {}} />
      </MemoryRouter>,
    );
  });
  await act(async () => host.querySelector<HTMLButtonElement>(".user-profile-trigger")!.click());
}

const item = () =>
  [...host.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) => el.textContent?.includes("Install app")) ??
  null;

beforeEach(() => {
  install.state = "can-prompt";
  vi.mocked(promptInstall).mockClear();
  vi.mocked(markInstallDone).mockClear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

describe("Install app in the profile menu", () => {
  it("comes first, above Activity", async () => {
    await openMenu();
    const items = [...host.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    expect(items[0]).toBe(item());
    expect(items.length).toBeGreaterThan(1);
  });

  it("opens the browser's install dialog once and remembers an accepted install", async () => {
    await openMenu();
    await act(async () => item()!.click());
    expect(promptInstall).toHaveBeenCalledTimes(1);
    expect(markInstallDone).toHaveBeenCalled();
  });

  it("shows the Add to Home Screen steps on an iPhone", async () => {
    install.state = "ios-manual";
    await openMenu();
    await act(async () => item()!.click());
    expect(promptInstall).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Add to Home Screen");
  });

  it("is not there when the app cannot be installed from here or already runs installed", async () => {
    for (const state of ["unavailable", "running-installed"]) {
      install.state = state;
      await openMenu();
      expect(item()).toBeNull();
      await act(async () => host.querySelector<HTMLButtonElement>(".user-profile-trigger")!.click());
    }
  });
});
