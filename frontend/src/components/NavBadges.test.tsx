/**
 * @vitest-environment happy-dom
 *
 * The Support count in the sidebar and on the topbar shortcut: drawn from
 * useTicketBadges, asked for only by a menu that has the item, and read out
 * with the item's name. Support stays the current item on a conversation.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const badges = vi.hoisted(() => ({ support: 0, tickets: 0, ticketsUrgent: false, asked: [] as string[][] }));

vi.mock("../hooks/useTicketBadges", async (importOriginal) => {
  const real = await importOriginal<typeof import("../hooks/useTicketBadges")>();
  return {
    ...real,
    useTicketBadges: (keys: string[]) => {
      badges.asked.push(keys);
      return { support: badges.support, tickets: badges.tickets, ticketsUrgent: badges.ticketsUrgent };
    },
  };
});
vi.mock("../api", () => ({ getCachedSession: () => null, onSessionReady: () => () => undefined }));
vi.mock("../lib/session", () => ({ getSessionUser: () => ({ username: "s.karimi", display_name: null, role: "user", loginAt: 0 }) }));
vi.mock("./UserProfile", () => ({ default: () => null }));

import SidebarNav from "./SidebarNav";
import TopbarNav from "./TopbarNav";
import { userSidebarNavForSession } from "../lib/userPanelNav";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  badges.support = 0;
  badges.tickets = 0;
  badges.ticketsUrgent = false;
  badges.asked = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(path: string, node: React.ReactNode) {
  await act(async () => {
    root.render(<MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>);
  });
}

const supportLink = () => host.querySelector<HTMLAnchorElement>('a[href="/app/support"]')!;

describe("the Support count", () => {
  it("shows in the sidebar, and Support stays current on a conversation", async () => {
    badges.support = 2;
    await render("/app/support/1042", <SidebarNav nav={userSidebarNavForSession(null)} />);
    expect(badges.asked.at(-1)).toEqual(["support"]);
    expect(supportLink().className).toContain("active");
    expect(supportLink().querySelector(".nav-count-badge")?.textContent).toBe("2, 2 tickets with a new reply");
    expect(host.querySelectorAll(".nav-count-badge")).toHaveLength(1);
  });

  it("is not drawn at zero, and nothing is asked for without the item", async () => {
    await render("/app/chat", <SidebarNav nav={userSidebarNavForSession({ features: { support: false } } as never)} />);
    expect(host.querySelector('a[href="/app/support"]')).toBeNull();
    expect(badges.asked.at(-1)).toEqual([]);
    await render("/app/chat", <SidebarNav nav={userSidebarNavForSession(null)} />);
    expect(host.querySelector(".nav-count-badge")).toBeNull();
  });

  it("shows on the topbar shortcut and joins its name", async () => {
    badges.support = 1;
    await render("/app/chat", <TopbarNav theme="dark" onThemeChange={() => undefined} />);
    expect(supportLink().getAttribute("aria-label")).toBe("Support, 1 ticket with a new reply");
    expect(supportLink().querySelector('.nav-count-badge [aria-hidden="true"]')?.textContent).toBe("1");
    expect(host.querySelector('a[href="/app/media"]')?.getAttribute("aria-label")).toBe("Media");
  });
});
