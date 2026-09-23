/**
 * @vitest-environment happy-dom
 *
 * The docs shell: contents beside the text on a desktop; on a phone the text
 * takes the width, the search sits in a bar with a Contents button, and the
 * contents open from it as a modal side sheet.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false }));
vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => layout.phone,
  useMediaQuery: () => false,
}));

import DocsShell, { buildDocNavGroups, type DocSectionDef } from "./DocsShell";

const sections: DocSectionDef[] = [
  {
    id: "intro",
    title: "Introduction",
    group: "Get started",
    content: <h1>Manual</h1>,
  },
  { id: "chat", title: "Chat overview", group: "Chat", content: <h2>Chat</h2> },
  {
    id: "media",
    title: "Media library",
    group: "Media",
    content: <h2>Media</h2>,
  },
];

let host: HTMLDivElement;
let root: Root;
const scrolled: string[] = [];
const realScrollIntoView = Element.prototype.scrollIntoView;

beforeEach(() => {
  layout.phone = false;
  scrolled.length = 0;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this.id);
  };
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = realScrollIntoView;
});

const render = () =>
  act(async () => {
    root.render(
      <MemoryRouter>
        <DocsShell
          sidebarLabel="User Manual"
          searchPlaceholder="Search manual…"
          sections={sections}
          navGroups={buildDocNavGroups(sections)}
        />
      </MemoryRouter>,
    );
  });
const contents = () => host.querySelector<HTMLElement>(".docs-sidebar")!;
const button = () =>
  host.querySelector<HTMLButtonElement>(".docs-contents-btn");
const search = () => host.querySelector<HTMLInputElement>(".docs-search")!;
const link = (title: string) =>
  [...host.querySelectorAll<HTMLButtonElement>(".docs-nav-link")].find(
    (b) => b.textContent === title,
  )!;
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

describe("the docs on a desktop", () => {
  it("keep the contents and the search beside the text, with no Contents button", async () => {
    await render();
    expect(button()).toBeNull();
    expect(contents().classList.contains("docs-sidebar--drawer")).toBe(false);
    expect(contents().hasAttribute("role")).toBe(false);
    expect(contents().querySelector(".docs-search")).toBe(search());
    expect(search().getAttribute("aria-label")).toBe("Search manual");
  });
});

describe("the docs on a phone", () => {
  beforeEach(() => {
    layout.phone = true;
  });

  it("put the search in a bar above the text and keep the contents closed", async () => {
    await render();
    expect(host.querySelector(".docs-phone-bar")?.contains(search())).toBe(
      true,
    );
    expect(contents().classList.contains("docs-sidebar--drawer")).toBe(true);
    expect(contents().classList.contains("is-open")).toBe(false);
    // Closed, it is not a dialog: the Shell's Escape looks for aria-modal layers.
    expect(contents().hasAttribute("aria-modal")).toBe(false);
    expect(button()?.getAttribute("aria-expanded")).toBe("false");
    expect(button()?.getAttribute("aria-controls")).toBe(contents().id);
  });

  it("open the contents as a modal sheet, focus the section being read, and go to a section", async () => {
    await render();
    await act(async () => button()!.click());
    expect(contents().classList.contains("is-open")).toBe(true);
    expect(contents().getAttribute("role")).toBe("dialog");
    expect(contents().getAttribute("aria-modal")).toBe("true");
    expect(contents().getAttribute("aria-label")).toBe("User Manual contents");
    expect(button()?.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(link("Introduction"));
    expect(link("Introduction").getAttribute("aria-current")).toBe("location");

    await act(async () => link("Media library").click());
    expect(scrolled).toEqual(["media"]);
    expect(contents().classList.contains("is-open")).toBe(false);
    expect(document.activeElement).toBe(button());
    expect(link("Media library").classList.contains("active")).toBe(true);
  });

  it("close on Escape, on the close button and on the backdrop, and keep Tab inside", async () => {
    await render();
    await act(async () => button()!.click());
    await key({ key: "Tab", shiftKey: true });
    expect(document.activeElement?.getAttribute("aria-label")).toBe(
      "Close contents",
    );
    await key({ key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(link("Media library"));
    await key({ key: "Tab" });
    expect(document.activeElement?.getAttribute("aria-label")).toBe(
      "Close contents",
    );
    await key({ key: "Escape" });
    expect(contents().classList.contains("is-open")).toBe(false);
    expect(document.activeElement).toBe(button());

    await act(async () => button()!.click());
    await act(async () =>
      host.querySelector<HTMLButtonElement>(".docs-contents-close")!.click(),
    );
    expect(contents().classList.contains("is-open")).toBe(false);

    await act(async () => button()!.click());
    await act(async () =>
      host.querySelector<HTMLElement>(".docs-contents-backdrop")!.click(),
    );
    expect(contents().classList.contains("is-open")).toBe(false);
    expect(host.querySelector(".docs-contents-backdrop")).toBeNull();
  });

  it("keep the text and the search's value when the width crosses the breakpoint", async () => {
    await render();
    const article = host.querySelector(".docs-main");
    // React tracks the value through the native setter; set it that way, then fire input.
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    await act(async () => {
      setValue.call(search(), "media");
      search().dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(
      [...host.querySelectorAll(".docs-section")].map((s) => s.id),
    ).toEqual(["media"]);
    await act(async () => button()!.click());
    layout.phone = false;
    await render();
    expect(host.querySelector(".docs-main")).toBe(article);
    expect(search().value).toBe("media");
    // An open sheet does not linger, to show itself on the next rotation.
    layout.phone = true;
    await render();
    expect(contents().classList.contains("is-open")).toBe(false);
  });
});
