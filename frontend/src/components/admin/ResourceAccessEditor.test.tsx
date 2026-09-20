/**
 * @vitest-environment happy-dom
 *
 * The editor is used in three places — Chat Tools, Agent Studio, Knowledge
 * Bases — and borrowed the Agent page's card styles, which assume a wide
 * column. In a 480px dialog the save button wrapped onto two lines, four
 * controls broke into a ragged 2x2, and "Visibility" rendered at the 16px
 * body size because a bare <label> has no rule anywhere in the stylesheet.
 *
 * None of that is visible to a DOM test, and this project has no visual
 * regression gate. What a test *can* hold is the contract the fix rests on:
 * the editor owns its own classes rather than the shared .agent-* ones, and
 * every label is a `.field`. If someone adds a fourth control with a bare
 * <label>, this fails.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn() }));

import { api } from "../../api";
import ResourceAccessEditor from "./ResourceAccessEditor";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockImplementation(async (path: string) =>
    path.endsWith("/access") ? { access_type: "public", acl_version: 3, grants: [] } : [],
  );
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
      <ResourceAccessEditor
        title="Who can use Web Fetch"
        loadPath="/api/admin/chat-tools/web_fetch/access"
        savePath="/api/admin/chat-tools/web_fetch/access"
      />,
    );
  });
}

describe("the access editor's layout contract", () => {
  it("owns its styles instead of borrowing the Agent page's card", async () => {
    await render();
    expect(host.querySelector(".resource-access-editor")).not.toBeNull();
    // Borrowing these is what made it assume a wide column.
    expect(host.querySelector(".agent-section-card")).toBeNull();
    expect(host.querySelector(".agent-inline-form")).toBeNull();
  });

  it("gives every control a labelled field", async () => {
    await render();
    const labels = [...host.querySelectorAll("label")];
    // Visibility, plus the three that make up a grant.
    expect(labels.length).toBe(4);
    // A label outside the primitive is a label at the body font size.
    expect(labels.every((label) => label.classList.contains("field"))).toBe(true);
  });

  it("keeps the grant controls in one row that is allowed to wrap", async () => {
    await render();
    const row = host.querySelector("form");
    expect(row?.classList.contains("field-row")).toBe(true);
    expect(row?.classList.contains("resource-access-editor__grant")).toBe(true);
  });

  it("still shows the rules and the ACL version it loaded", async () => {
    await render();
    expect(host.textContent).toContain("Deny always wins");
    expect(host.textContent).toContain("ACL v3");
  });

  it("still switches the target control with the target type", async () => {
    await render();
    // Selects in order: Visibility, then the grant's target type.
    const typeSelect = host.querySelectorAll("select")[1] as HTMLSelectElement;
    // No groups came back, so a group target falls back to a free-text box.
    expect(host.querySelector("input")).not.toBeNull();

    await act(async () => {
      typeSelect.value = "department";
      typeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelector("input")?.getAttribute("placeholder")).toBe("Department name");
  });
});
