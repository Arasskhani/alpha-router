/**
 * @vitest-environment happy-dom
 *
 * Row actions: a popover next to the button on a desktop, an action sheet
 * along the bottom edge on a phone.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false }));
vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => layout.phone,
  useMediaQuery: () => false,
}));
vi.mock("../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));

import RowActionsMenu, { type RowAction } from "./RowActionsMenu";

let host: HTMLDivElement;
let root: Root;
let calls: string[];
let actions: RowAction[];

beforeEach(() => {
  layout.phone = false;
  calls = [];
  actions = [
    { label: "Edit", onClick: () => void calls.push("edit") },
    { label: "Hidden", onClick: () => void calls.push("hidden"), disabled: true },
    { label: "Delete", onClick: () => void calls.push("delete"), danger: true },
  ];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const render = () =>
  act(async () => {
    root.render(<RowActionsMenu actions={actions} label="Actions" />);
  });
const trigger = () => host.querySelector<HTMLButtonElement>(".row-actions-trigger")!;
const sheet = () => document.querySelector<HTMLElement>(".action-sheet");
const popover = () => document.querySelector<HTMLElement>(".row-actions-menu--portal");
const itemLabels = (el: Element | null) => [...(el?.querySelectorAll('[role="menuitem"]') ?? [])].map((b) => b.textContent);
const press = (el: Element | null, type = "click") =>
  act(async () => {
    if (!el) throw new Error("nothing to press");
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
  });

describe("row actions on a desktop", () => {
  it("open as a popover next to the button", async () => {
    await render();
    await press(trigger());
    expect(popover()).not.toBeNull();
    expect(sheet()).toBeNull();
    expect(itemLabels(popover())).toEqual(["Edit", "Delete"]);
  });
});

describe("row actions on a phone", () => {
  beforeEach(() => {
    layout.phone = true;
  });

  it("open as an action sheet with the enabled actions and Cancel, focus inside", async () => {
    await render();
    await press(trigger());
    expect(popover()).toBeNull();
    expect(sheet()?.getAttribute("role")).toBe("menu");
    expect(sheet()?.getAttribute("aria-label")).toBe("Actions");
    expect(itemLabels(sheet())).toEqual(["Edit", "Delete", "Cancel"]);
    expect(sheet()!.querySelector(".action-sheet__item--danger")?.textContent).toBe("Delete");
    expect(document.activeElement?.textContent).toBe("Edit");
  });

  it("run an action and close", async () => {
    await render();
    await press(trigger());
    await press([...sheet()!.querySelectorAll("button")].find((b) => b.textContent === "Delete")!);
    expect(calls).toEqual(["delete"]);
    expect(sheet()).toBeNull();
  });

  it("close on Cancel, on Escape and on the backdrop, and hand focus back to the button", async () => {
    await render();
    await press(trigger());
    await press([...sheet()!.querySelectorAll("button")].find((b) => b.textContent === "Cancel")!);
    expect(sheet()).toBeNull();
    expect(document.activeElement).toBe(trigger());

    await press(trigger());
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(sheet()).toBeNull();

    await press(trigger());
    const backdrop = document.querySelector(".action-sheet-backdrop");
    // A tap on the backdrop: the mousedown must not close it early (the click
    // would then land on the page underneath); the click closes it.
    await press(backdrop, "mousedown");
    expect(sheet()).not.toBeNull();
    await press(backdrop);
    expect(sheet()).toBeNull();
    expect(calls).toEqual([]);
  });

  it("close when the user taps elsewhere on the page", async () => {
    await render();
    await press(trigger());
    await press(document.body, "mousedown");
    expect(sheet()).toBeNull();
  });
});
