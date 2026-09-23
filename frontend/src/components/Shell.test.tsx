/**
 * @vitest-environment happy-dom
 *
 * The shell on a phone: the side panel is a drawer behind the topbar's menu
 * button. On every page but chat that panel is the navigation and Shell owns
 * it; on the chat page it is the chat history, which ChatPanel renders from
 * the state Shell publishes through ShellMenuContext.
 */
import { StrictMode, act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Link, MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false, tablet: false }));

vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  NAV_DRAWER_QUERY: "(max-width: 1024px)",
  usePhoneLayout: () => layout.phone,
  // A phone is narrower than a tablet: the drawer query holds for both.
  useMediaQuery: (query: string) => query === "(max-width: 1024px)" && (layout.phone || layout.tablet),
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
  const navigate = useNavigate();
  const [dialog, setDialog] = useState(false);
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
      <button type="button" onClick={() => navigate("/app/projects")}>
        go to projects
      </button>
      <Link to="/app/projects/p1">to a workspace tab</Link>
      <input type="search" aria-label="Search chats" />
      <button type="button" onClick={() => setDialog(true)}>
        open dialog
      </button>
      {dialog ? (
        <div role="dialog" aria-modal="true">
          <button type="button" onClick={() => setDialog(false)}>
            close dialog
          </button>
        </div>
      ) : null}
    </div>
  );
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  layout.phone = false;
  layout.tablet = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

// StrictMode mounts effects twice: the drawer claim must survive that.
async function render(path: string) {
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/app" element={<Shell nav={NAV} />}>
              <Route path="chat" element={<ChatProbe />} />
              <Route path="projects" element={<h1>Projects page</h1>} />
              <Route path="projects/:projectId" element={<ChatProbe claim={false} />} />
            </Route>
            <Route path="/admin" element={<Shell nav={NAV} />}>
              <Route path="users" element={<h1>Users page</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );
  });
}

const buttonNamed = (label: string) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) ?? null;
const probeText = () => document.querySelector('[data-testid="probe"]')?.textContent;

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

  it("has no bottom tab bar", async () => {
    await render("/app/projects");
    expect(document.querySelector(".bottom-tab-bar")).toBeNull();
  });
});

describe("the shell on a tablet (769–1024px)", () => {
  beforeEach(() => {
    layout.tablet = true;
  });

  it("puts the navigation in the drawer instead of a block above the page", async () => {
    await render("/admin/users");
    const aside = sidebar()!;
    expect(aside.classList.contains("sidebar--drawer")).toBe(true);
    expect(aside.getAttribute("aria-hidden")).toBe("true");
    await click(menuButton());
    expect(aside.classList.contains("is-open")).toBe(true);
    expect(document.activeElement).toBe(aside);
    await escape();
    expect(aside.classList.contains("is-open")).toBe(false);
    expect(document.activeElement).toBe(menuButton());
  });

  it("keeps the full logo and has no bottom tab bar", async () => {
    await render("/app/projects");
    expect(menuButton()).not.toBeNull();
    expect(document.querySelector(".bottom-tab-bar")).toBeNull();
    expect(document.querySelector('[data-testid="probe"]')).toBeNull();
  });

  it("leaves the chat pages as on a desktop: no menu button, and the history is no drawer", async () => {
    await render("/app/chat");
    expect(menuButton()).toBeNull();
    expect(probeText()).toBe("phone=false open=false");
  });

  it("closes the drawer when a link in it leads to the chat page, which has none", async () => {
    await render("/app/projects");
    await click(menuButton());
    const chat = [...document.querySelectorAll<HTMLAnchorElement>(".sidebar--drawer a")].find(
      (a) => a.textContent?.trim() === "Chat",
    );
    await click(chat ?? null);
    expect(probeText()).toBe("phone=false open=false");
    expect(menuButton()).toBeNull();
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

  it("renders no navigation drawer while the panel holds the claim, and one again once it lets go", async () => {
    await render("/app/chat");
    expect(sidebar()).toBeNull();
    // Leaving the chat page unmounts the claimant: the button falls back to the navigation.
    await click(document.querySelector("a[href='/app/projects/p1']"));
    expect(sidebar()?.classList.contains("sidebar--drawer")).toBe(true);
    await click(menuButton());
    expect(sidebar()?.classList.contains("is-open")).toBe(true);
  });

  it("closes the drawer when the page navigates by itself", async () => {
    await render("/app/chat");
    await click(menuButton());
    expect(probeText()).toBe("phone=true open=true");
    await click(buttonNamed("go to projects"));
    expect(document.querySelector("h1")?.textContent).toBe("Projects page");
    expect(sidebar()?.classList.contains("is-open")).toBe(false);
  });

  it("the menu button closes the navigation and the history together", async () => {
    await render("/app/chat");
    await click(menuButton());
    await click(buttonNamed("open navigation"));
    expect(menuButton()?.getAttribute("aria-expanded")).toBe("true");
    await click(menuButton());
    expect(document.querySelector(".sidebar--flyout")?.classList.contains("is-open")).toBe(false);
    expect(probeText()).toBe("phone=true open=false");
    expect(menuButton()?.getAttribute("aria-expanded")).toBe("false");
  });

  it("forgets an open navigation flyout too when the layout widens", async () => {
    await render("/app/chat");
    await click(menuButton());
    await click(buttonNamed("open navigation"));
    layout.phone = false;
    await render("/app/chat");
    expect(document.querySelector(".sidebar--flyout")?.classList.contains("is-open")).toBe(false);
    layout.phone = true;
    await render("/app/chat");
    expect(document.querySelector(".sidebar--flyout")?.classList.contains("is-open")).toBe(false);
    expect(backdrop()).toBeNull();
  });

  it("leaves Escape to a dialog, a menu or a search field that has text", async () => {
    await render("/app/chat");
    await click(menuButton());
    await click(buttonNamed("open dialog"));
    await escape();
    expect(probeText()).toBe("phone=true open=true");
    await click(buttonNamed("close dialog"));

    const search = document.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = "budget";
    await act(async () => {
      search.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(probeText()).toBe("phone=true open=true");
    search.value = "";
    await act(async () => {
      search.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(probeText()).toBe("phone=true open=false");
  });

  it("moves focus into the navigation flyout and back to what opened it", async () => {
    await render("/app/chat");
    await click(menuButton());
    const opener = buttonNamed("open navigation")!;
    opener.focus();
    await click(opener);
    const flyout = document.querySelector<HTMLElement>(".sidebar--flyout")!;
    expect(document.activeElement).toBe(flyout);
    expect(flyout.getAttribute("aria-hidden")).toBeNull();
    await escape();
    expect(document.activeElement).toBe(opener);
    expect(flyout.getAttribute("aria-hidden")).toBe("true");
  });

  it("puts the user sections in a bottom tab bar, below the page", async () => {
    await render("/app/chat");
    const tabs = document.querySelector(".layout > .bottom-tab-bar");
    expect(tabs).not.toBeNull();
    expect(tabs?.previousElementSibling?.className).toBe("layout-body");
  });

  it("has no bottom tab bar in the admin panel", async () => {
    await render("/admin/users");
    expect(document.querySelector("h1")?.textContent).toBe("Users page");
    expect(document.querySelector(".bottom-tab-bar")).toBeNull();
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
