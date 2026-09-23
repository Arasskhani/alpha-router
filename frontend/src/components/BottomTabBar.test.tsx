/**
 * @vitest-environment happy-dom
 *
 * The phone's bottom tab bar: four user sections plus "More", which opens a
 * sheet with the rest (the manual, and Administration for admins). It steps
 * aside while a field has the keyboard up.
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ admin: false }));

vi.mock("../api", () => ({ getCachedSession: () => null }));
vi.mock("../lib/userPanelNav", async (importOriginal) => {
  const real = await importOriginal<typeof import("../lib/userPanelNav")>();
  return {
    ...real,
    topbarShortcutsForSession: () =>
      session.admin
        ? [...real.USER_SIDEBAR_NAV, { to: "/admin/users", label: "Administration", icon: "admin" as const }]
        : [...real.USER_SIDEBAR_NAV],
  };
});

import BottomTabBar from "./BottomTabBar";

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  session.admin = false;
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
      <StrictMode>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <input aria-label="Message" />
                  <input type="checkbox" aria-label="Pick" />
                  <textarea aria-label="Notes" />
                  <Where />
                  <BottomTabBar />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );
  });
}

const bar = () => document.querySelector<HTMLElement>(".bottom-tab-bar");
const tabLabels = () => [...(bar()?.querySelectorAll(".bottom-tab__label") ?? [])].map((el) => el.textContent);
const current = () => bar()?.querySelector('[aria-current="page"] .bottom-tab__label')?.textContent ?? null;
const moreButton = () => bar()?.querySelector<HTMLButtonElement>("button") ?? null;
const sheet = () => document.querySelector<HTMLElement>(".bottom-sheet");
const where = () => document.querySelector('[data-testid="where"]')?.textContent;
const field = (label: string) => document.querySelector<HTMLElement>(`[aria-label="${label}"]`)!;
const click = (el: Element | null) =>
  act(async () => {
    if (!el) throw new Error("nothing to click");
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));
  });
const focus = (el: HTMLElement) => act(async () => el.focus());
const blur = (el: HTMLElement) => act(async () => el.blur());

describe("the bottom tab bar", () => {
  it("lists four sections and More, and marks the one the page is in", async () => {
    await render("/app/projects/p1");
    expect(tabLabels()).toEqual(["Chat", "Projects", "Media", "Activity", "More"]);
    expect(current()).toBe("Projects");
    await click(bar()!.querySelector('a[href="/app/media"]'));
    expect(where()).toBe("/app/media");
    expect(current()).toBe("Media");
  });

  it("hides while a text field has focus, and not for a checkbox", async () => {
    await render("/app/chat");
    await focus(field("Message"));
    expect(bar()).toBeNull();
    // Moving on to the next field does not flash the bar in between.
    await focus(field("Notes"));
    expect(bar()).toBeNull();
    await blur(field("Notes"));
    expect(bar()).not.toBeNull();
    await focus(field("Pick"));
    expect(bar()).not.toBeNull();
  });

  it("opens More as a sheet with the other sections, and focus goes in and back", async () => {
    session.admin = true;
    await render("/app/chat");
    expect(moreButton()?.getAttribute("aria-expanded")).toBe("false");
    await click(moreButton());
    expect(moreButton()?.getAttribute("aria-expanded")).toBe("true");
    expect(sheet()?.getAttribute("aria-modal")).toBe("true");
    const items = [...sheet()!.querySelectorAll("a")].map((a) => a.textContent);
    expect(items).toEqual(["User Manual", "Administration"]);
    expect(document.activeElement).toBe(sheet()!.querySelector("a"));

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(sheet()).toBeNull();
    expect(document.activeElement).toBe(moreButton());
  });

  it("closes the sheet on the backdrop and when one of its links is followed", async () => {
    await render("/app/chat");
    await click(moreButton());
    await click(document.querySelector(".bottom-sheet-backdrop"));
    expect(sheet()).toBeNull();

    await click(moreButton());
    await click(sheet()!.querySelector('a[href="/app/manual"]'));
    expect(sheet()).toBeNull();
    expect(where()).toBe("/app/manual");
    // A page under More lights up the More tab.
    expect(moreButton()?.classList.contains("is-active")).toBe(true);
  });
});
