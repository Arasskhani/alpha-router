/**
 * @vitest-environment happy-dom
 *
 * The shell on a phone: the side panel is a drawer behind the topbar's menu
 * button. On every page but chat that panel is the navigation and Shell owns
 * it; on the chat page it is the chat history, which ChatPanel renders from
 * the state Shell publishes through ShellMenuContext.
 */
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false }));

vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => layout.phone,
  useMediaQuery: () => false,
}));
vi.mock("../hooks/usePresenceHeartbeat", () => ({ default: () => {} }));
vi.mock("../lib/session", () => ({ getSessionUser: () => null }));
vi.mock("../lib/chatStorage", () => ({
  hydrateUserPrefsFromServer: () => new Promise(() => {}),
  saveThemeToServer: () => Promise.resolve(),
}));
vi.mock("./TopbarNav", () => ({ default: () => <div data-testid="topbar-nav" /> }));

import Shell from "./Shell";
import { useShellMenu } from "../context/ShellMenuContext";

const NAV = [
  { to: "/app/chat", label: "Chat", icon: "chat" as const },
  { to: "/app/projects", label: "Projects", icon: "projects" as const },
];

/** Stands in for ChatPanel: claims the drawer, shows what Shell publishes and can act on it. */
function ChatProbe({ claim = true }: { claim?: boolean }) {
  const menu = useShellMenu();
  const claimDrawer = menu?.claimDrawer;
  useEffect(() => {
    if (!claim || !claimDrawer) return undefined;
    return claimDrawer();
  }, [claim, claimDrawer]);
  return (
    <div>
      <output data-testid="probe">{`phone=${menu?.phone} open=${menu?.drawerOpen}`}</output>
      <button type="button" onClick={() => menu?.closeDrawer()}>
        close history
      </button>
      <button type="button" onClick={() => menu?.openAdminMenu()}>
        open navigation
      </button>
    </div>
  );
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  layout.phone = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app" element={<Shell nav={NAV} />}>
            <Route path="chat" element={<ChatProbe />} />
            <Route path="projects" element={<h1>Projects page</h1>} />
            <Route path="projects/:projectId" element={<ChatProbe claim={false} />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  });
}

const menuButton = () => document.querySelector<HTMLButtonElement>(".topbar-menu-btn");
const sidebar = () => document.querySelector<HTMLElement>(".layout-body .sidebar:not(.sidebar--flyout)");
const backdrop = () => document.querySelector<HTMLElement>(".shell-drawer-backdrop");
const click = (el: Element | null) =>
  act(async () => {
    if (!el) throw new Error("nothing to click");
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
const escape = () =>
  act(async () => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });

describe("the shell on a desktop", () => {
  it("shows the navigation in the page, with no menu button", async () => {
    await render("/app/projects");
    expect(menuButton()).toBeNull();
    expect(sidebar()?.className).toBe("sidebar");
    expect(sidebar()?.getAttribute("aria-hidden")).toBeNull();
    expect(backdrop()).toBeNull();
  });
});

describe("the shell on a phone", () => {
  beforeEach(() => {
    layout.phone = true;
  });

  it("keeps the navigation in a closed drawer until the menu button opens it", async () => {
    await render("/app/projects");
    const aside = sidebar()!;
    expect(aside.classList.contains("sidebar--drawer")).toBe(true);
    expect(aside.classList.contains("is-open")).toBe(false);
    expect(aside.getAttribute("aria-hidden")).toBe("true");
    expect(menuButton()?.getAttribute("aria-expanded")).toBe("false");
    expect(menuButton()?.getAttribute("aria-controls")).toBe(aside.id);

    await click(menuButton());
    expect(aside.classList.contains("is-open")).toBe(true);
    expect(aside.getAttribute("aria-hidden")).toBeNull();
    expect(menuButton()?.getAttribute("aria-expanded")).toBe("true");
    expect(backdrop()).not.toBeNull();
    expect(document.activeElement).toBe(aside);
  });

  it("closes on the backdrop, on Escape, and hands focus back to the button", async () => {
    await render("/app/projects");
    await click(menuButton());
    await click(backdrop());
    expect(sidebar()?.classList.contains("is-open")).toBe(false);
    expect(backdrop()).toBeNull();
    expect(document.activeElement).toBe(menuButton());

    await click(menuButton());
    await escape();
    expect(sidebar()?.classList.contains("is-open")).toBe(false);
  });

  it("closes when a link in it is followed", async () => {
    await render("/app/projects");
    await click(menuButton());
    const link = [...document.querySelectorAll<HTMLAnchorElement>(".sidebar--drawer a")].find(
      (a) => a.textContent?.trim() === "Chat",
    );
    await click(link ?? null);
    expect(document.querySelector('[data-testid="probe"]')?.textContent).toBe("phone=true open=false");
  });

  it("closes again when the layout widens to a desktop", async () => {
    await render("/app/projects");
    await click(menuButton());
    expect(sidebar()?.classList.contains("is-open")).toBe(true);
    layout.phone = false;
    await render("/app/projects");
    expect(menuButton()).toBeNull();
    expect(sidebar()?.className).toBe("sidebar");
    layout.phone = true;
    await render("/app/projects");
    expect(sidebar()?.classList.contains("is-open")).toBe(false);
  });

  it("on the chat page publishes the drawer state instead of rendering the panel", async () => {
    await render("/app/chat");
    expect(sidebar()).toBeNull();
    const probe = () => document.querySelector('[data-testid="probe"]')?.textContent;
    expect(probe()).toBe("phone=true open=false");
    await click(menuButton());
    expect(probe()).toBe("phone=true open=true");
    // ChatPanel closes it after a chat is picked.
    await click([...document.querySelectorAll("button")].find((b) => b.textContent === "close history") ?? null);
    expect(probe()).toBe("phone=true open=false");
    await click(menuButton());
    await escape();
    expect(probe()).toBe("phone=true open=false");
  });

  it("stacks the navigation over the chat history and closes the top layer first", async () => {
    await render("/app/chat");
    await click(menuButton());
    const buttons = [...document.querySelectorAll("button")];
    await click(buttons.find((b) => b.textContent === "open navigation") ?? null);
    const flyout = document.querySelector(".sidebar--flyout");
    expect(flyout?.classList.contains("is-open")).toBe(true);
    expect(backdrop()?.classList.contains("shell-drawer-backdrop--over")).toBe(true);

    await escape();
    expect(flyout?.classList.contains("is-open")).toBe(false);
    expect(document.querySelector('[data-testid="probe"]')?.textContent).toBe("phone=true open=true");
    await escape();
    expect(document.querySelector('[data-testid="probe"]')?.textContent).toBe("phone=true open=false");
  });

  it("a tap outside the navigation flyout closes only the flyout", async () => {
    await render("/app/chat");
    await click(menuButton());
    await click([...document.querySelectorAll("button")].find((b) => b.textContent === "open navigation") ?? null);
    await click(backdrop());
    expect(document.querySelector(".sidebar--flyout")?.classList.contains("is-open")).toBe(false);
    expect(document.querySelector('[data-testid="probe"]')?.textContent).toBe("phone=true open=true");
  });

  it("opens the navigation when no panel on a chat-layout page claims the button", async () => {
    // A project workspace tab without the chat history, say.
    await render("/app/projects/p1");
    const probe = () => document.querySelector('[data-testid="probe"]')?.textContent;
    expect(sidebar()?.classList.contains("sidebar--drawer")).toBe(true);
    await click(menuButton());
    expect(sidebar()?.classList.contains("is-open")).toBe(true);
    expect(backdrop()).not.toBeNull();
    // The page still sees the state, but the navigation is what opened.
    expect(probe()).toBe("phone=true open=true");
    await click(backdrop());
    expect(sidebar()?.classList.contains("is-open")).toBe(false);
  });

  it("renders no navigation drawer on a chat-layout page once the panel claims the button", async () => {
    await render("/app/chat");
    expect(sidebar()).toBeNull();
    layout.phone = false;
    await render("/app/projects/p1");
    expect(sidebar()).toBeNull();
    expect(menuButton()).toBeNull();
  });

  it("shows the brand mark alone in the topbar", async () => {
    await render("/app/projects");
    expect(document.querySelector(".topbar-brand .alpha-router-logo-alpha-rest")).toBeNull();
    expect(document.querySelector(".topbar-brand .alpha-router-logo-mark")).not.toBeNull();
    layout.phone = false;
    await render("/app/projects");
    expect(document.querySelector(".topbar-brand .alpha-router-logo-alpha-rest")).not.toBeNull();
  });
});
