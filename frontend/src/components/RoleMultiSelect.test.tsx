/**
 * @vitest-environment happy-dom
 *
 * The role picker: a popover beside its trigger on a desktop, a sheet from
 * the bottom edge on a phone.
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

import type { RoleRecord } from "../lib/rbac";
import RoleMultiSelect from "./RoleMultiSelect";

const role = (slug: string, name: string): RoleRecord => ({
  slug,
  name,
  description: "",
  category: "General",
  category_key: null,
  menu_key: null,
  read_only: false,
  is_user_panel: false,
});
const roles = [
  role("user", "User"),
  role("full_administrator", "Administrator"),
  role("auditor", "Auditor"),
];

let host: HTMLDivElement;
let root: Root;
let changes: string[][];

beforeEach(() => {
  layout.phone = false;
  changes = [];
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
    root.render(
      <RoleMultiSelect
        value={["user"]}
        roles={roles}
        onChange={(next) => changes.push(next)}
      />,
    );
  });
const open = async () => {
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(".role-multi-select__trigger")!
      .click(),
  );
  // Focus moves in on the next tick.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};
const panel = () =>
  document.querySelector<HTMLElement>(".role-multi-select__menu");
const press = (el: Element | null, type = "click") =>
  act(async () => {
    if (!el) throw new Error("nothing to press");
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
  });

describe("the role picker on a desktop", () => {
  it("opens as a popover beside the trigger, with the search focused", async () => {
    await render();
    await open();
    expect(panel()?.classList.contains("role-multi-select__menu--portal")).toBe(
      true,
    );
    expect(panel()?.style.position).toBe("fixed");
    expect(panel()?.hasAttribute("aria-modal")).toBe(false);
    expect(document.querySelector(".action-sheet-backdrop")).toBeNull();
    expect(document.activeElement).toBe(
      document.querySelector(".role-multi-select__search"),
    );
  });
});

describe("the role picker on a phone", () => {
  beforeEach(() => {
    layout.phone = true;
  });

  it("opens as a modal sheet, focus on the first role rather than the search", async () => {
    await render();
    await open();
    expect(panel()?.classList.contains("role-multi-select__menu--sheet")).toBe(
      true,
    );
    expect(panel()?.getAttribute("style")).toBeNull();
    expect(panel()?.getAttribute("aria-modal")).toBe("true");
    // The search would bring the keyboard up over the sheet.
    expect(document.activeElement).toBe(
      panel()!.querySelector(".role-multi-select__option input"),
    );
  });

  it("applies the roles picked, and keeps Tab inside", async () => {
    await render();
    await open();
    const boxes = [
      ...panel()!.querySelectorAll<HTMLInputElement>(
        ".role-multi-select__option input",
      ),
    ];
    const key = (init: KeyboardEventInit) =>
      act(async () => {
        document.dispatchEvent(
          new KeyboardEvent("keydown", {
            bubbles: true,
            cancelable: true,
            ...init,
          }),
        );
      });
    await key({ key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(
      panel()!.querySelector(".role-multi-select__search"),
    );
    await key({ key: "Tab", shiftKey: true });
    expect(document.activeElement?.textContent).toBe("Cancel");
    await key({ key: "Tab" });
    expect(document.activeElement).toBe(
      panel()!.querySelector(".role-multi-select__search"),
    );
    // Administrator is first, sorted by name.
    await press(boxes[0]);
    await press(
      [...panel()!.querySelectorAll("button")].find(
        (b) => b.textContent === "Apply",
      )!,
    );
    expect(changes).toEqual([["user", "full_administrator"]]);
    expect(panel()).toBeNull();
  });

  it("closes on a tap on the backdrop without the tap reaching the page", async () => {
    await render();
    await open();
    const backdrop = document.querySelector(".action-sheet-backdrop");
    // Closing on mousedown would let the same tap land on the page under the backdrop.
    await press(backdrop, "mousedown");
    expect(panel()).not.toBeNull();
    await press(backdrop);
    expect(panel()).toBeNull();
    expect(changes).toEqual([]);
  });
});
