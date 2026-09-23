/**
 * @vitest-environment happy-dom
 *
 * The Media page on a phone: the filters fold behind one button, the bulk
 * actions sit in one action sheet, and the cards fit. A desktop keeps its
 * toolbar as it was.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false, readOnly: false }));
vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => layout.phone,
  useMediaQuery: () => false,
}));
vi.mock("../context/ReadOnlyContext", () => ({
  useReadOnly: () => layout.readOnly,
}));
vi.mock("../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: async () => false }),
}));
vi.mock("../components/AuthenticatedImage", () => ({
  default: () => <span data-testid="img" />,
}));
vi.mock("../components/AuthenticatedVideo", () => ({
  default: () => <span data-testid="video" />,
}));
vi.mock("../components/MediaViewerModal", () => ({ default: () => null }));

const items = [1, 2].map((id) => ({
  id,
  kind: "image",
  mime_type: "image/png",
  file_name: `image-${id}.png`,
  url: `/api/user/media/${id}/file`,
  size_bytes: 9000,
  created_at: "2026-09-23T10:00:00Z",
  source_prompt: `Prompt ${id}`,
  content_hash: `hash-${id}`,
}));
vi.mock("../api", () => ({
  api: async (path: string) => {
    if (path.includes("/quota"))
      return { used_bytes: 18000, quota_bytes: 1_000_000_000, file_count: 2 };
    if (path.includes("/schedule"))
      return {
        cleanup_enabled: false,
        cleanup_retention_days: 30,
        cleanup_hour: 3,
        cleanup_minute: 0,
      };
    return { items, total: items.length };
  },
  authFetch: async () => new Response(""),
}));

import MediaLibrary from "./MediaLibrary";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  layout.phone = false;
  layout.readOnly = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <MediaLibrary />
      </MemoryRouter>,
    );
  });
  // Let the page's loads settle.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const filters = () => host.querySelector<HTMLElement>(".media-page-filters")!;
const searchBox = () =>
  host.querySelector<HTMLInputElement>(".media-page-search")!;
const refresh = () =>
  [...filters().querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === "Refresh",
  )!;

describe("the Media filters", () => {
  it("stay in sight on a desktop", async () => {
    await render();
    expect(filters().querySelector(".filter-panel-toggle")).toBeNull();
    expect(searchBox().closest(".filter-panel")?.hasAttribute("hidden")).toBe(
      false,
    );
  });

  it("fold behind one button on a phone, with Refresh left in sight", async () => {
    layout.phone = true;
    await render();
    const toggle = filters().querySelector<HTMLButtonElement>(
      ".filter-panel-toggle",
    );
    expect(toggle).not.toBeNull();
    expect(searchBox().closest(".filter-panel")?.hasAttribute("hidden")).toBe(
      true,
    );
    expect(refresh().closest(".filter-panel")).toBeNull();
    await act(async () => toggle!.click());
    expect(searchBox().closest(".filter-panel")?.hasAttribute("hidden")).toBe(
      false,
    );
  });
});

const actionsRow = () =>
  host.querySelector<HTMLElement>(".media-page-actions")!;
const buttonTexts = () =>
  [...actionsRow().querySelectorAll(":scope > button")].map((b) =>
    b.textContent?.trim(),
  );
const sheetItems = () =>
  [...document.querySelectorAll(".action-sheet [role=menuitem]")].map(
    (b) => b.textContent,
  );

describe("the Media cards", () => {
  it("mark their Open button, which a phone drops in the grid views", async () => {
    await render();
    const open = [
      ...host.querySelectorAll(".media-page-item__actions button"),
    ].filter((b) => b.classList.contains("media-page-item__open"));
    expect(open.map((b) => b.textContent?.trim())).toEqual(["Open", "Open"]);
  });
});

describe("the Media bulk actions", () => {
  it("are five buttons on a desktop", async () => {
    await render();
    expect(buttonTexts()).toEqual([
      "Download selected",
      "Download all (filtered)",
      "Delete selected",
      "Schedule cleanup",
      "Delete all",
    ]);
  });

  it("are one action sheet on a phone, offering what applies now", async () => {
    layout.phone = true;
    await render();
    expect(buttonTexts()).toEqual([]);
    const trigger = actionsRow().querySelector<HTMLButtonElement>(
      ".row-actions-trigger",
    )!;
    expect(trigger.textContent).toContain("Actions");
    await act(async () => trigger.click());
    // Nothing selected yet: no "selected" actions.
    expect(sheetItems()).toEqual([
      "Download all (filtered)",
      "Schedule cleanup",
      "Delete all",
      "Cancel",
    ]);
    await act(async () =>
      [
        ...document.querySelectorAll<HTMLButtonElement>(
          ".action-sheet [role=menuitem]",
        ),
      ]
        .find((b) => b.textContent === "Cancel")!
        .click(),
    );
    await act(async () =>
      actionsRow()
        .querySelector<HTMLInputElement>("input[type=checkbox]")!
        .click(),
    );
    await act(async () => trigger.click());
    expect(sheetItems()).toEqual([
      "Download selected",
      "Download all (filtered)",
      "Delete selected",
      "Schedule cleanup",
      "Delete all",
      "Cancel",
    ]);
  });

  it("stay download buttons for a read-only admin on a phone", async () => {
    layout.phone = true;
    layout.readOnly = true;
    await render();
    expect(actionsRow().querySelector(".row-actions-trigger")).toBeNull();
    expect(buttonTexts()).toEqual([
      "Download selected",
      "Download all (filtered)",
    ]);
  });
});
