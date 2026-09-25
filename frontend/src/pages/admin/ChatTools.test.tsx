/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));
// The browser extension card has its own tests (ExtensionSettingsCard.test.tsx) and its own requests.
vi.mock("../../components/admin/ExtensionSettingsCard", () => ({ default: () => <div data-testid="extension-card" /> }));

import { api } from "../../api";
import ChatTools from "./ChatTools";

const row = (over: Record<string, unknown> = {}) => ({
  key: "web_search",
  title: "Web Search",
  description: "Fresh web results",
  icon: "globe",
  access_type: "public",
  acl_version: 0,
  allow_count: 0,
  deny_count: 0,
  updated_at: null,
  ...over,
});

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
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
        <ChatTools />
      </MemoryRouter>,
    );
  });
}

describe("the Chat Tools page", () => {
  it("draws a row for whatever the server lists, without knowing the tools", async () => {
    // The point of the registry: a tool this file has never heard of still
    // gets a row, a readable name and a way to restrict it.
    vi.mocked(api).mockResolvedValueOnce([
      row(),
      row({ key: "brand_new_tool", title: "Brand New Tool", icon: "not_a_known_icon" }),
    ]);
    await render();
    expect(host.textContent).toContain("Web Search");
    expect(host.textContent).toContain("Brand New Tool");
    expect(host.querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("says who can use each tool in words rather than in counts", async () => {
    vi.mocked(api).mockResolvedValueOnce([
      row(),
      row({ key: "code_interpreter", title: "Code Interpreter", access_type: "private", allow_count: 2 }),
      row({ key: "web_fetch", title: "Web Fetch", access_type: "public", deny_count: 1 }),
    ]);
    await render();
    expect(host.textContent).toContain("Everyone");
    expect(host.textContent).toContain("Restricted — 2 grants");
    expect(host.textContent).toContain("Everyone except 1 exception");
  });

  it("opens the access editor for the tool whose button was pressed", async () => {
    vi.mocked(api).mockResolvedValueOnce([row({ key: "code_interpreter", title: "Code Interpreter" })]);
    await render();

    // The editor loads its own state plus the group and role directories.
    vi.mocked(api).mockImplementation(async (path: string) =>
      path.endsWith("/access") ? { access_type: "public", acl_version: 0, grants: [] } : [],
    );
    const manage = [...host.querySelectorAll("button")].find((b) => b.textContent === "Manage access");
    await act(async () => manage?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

    expect(document.body.textContent).toContain("Who can use Code Interpreter");
  });

  it("opens that editor in a dialog wide enough for it", async () => {
    // The default 480px panel wrapped the save button onto two lines and broke
    // the four grant controls into a ragged 2x2.
    vi.mocked(api).mockResolvedValueOnce([row()]);
    await render();
    vi.mocked(api).mockImplementation(async (path: string) =>
      path.endsWith("/access") ? { access_type: "public", acl_version: 0, grants: [] } : [],
    );
    const manage = [...host.querySelectorAll("button")].find((b) => b.textContent === "Manage access");
    await act(async () => manage?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

    expect(document.querySelector(".modal-panel--md")).not.toBeNull();
  });

  it("holds the browser extension's settings below the table", async () => {
    vi.mocked(api).mockResolvedValueOnce([row()]);
    await render();
    expect(host.querySelector("[data-testid='extension-card']")).not.toBeNull();
  });

  it("reports a failed load instead of showing an empty table", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("nope"));
    await render();
    expect(host.querySelector(".alert-error")?.textContent).toContain("nope");
  });
});
