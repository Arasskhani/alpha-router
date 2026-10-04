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
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { api } from "../../api";
import { decisionText, featureSummary } from "../../lib/featureAccess";
import FeatureAccess from "./FeatureAccess";

const rule = (over: Record<string, unknown> = {}) => ({
  id: 7,
  feature: "chat",
  target_type: "group",
  target: 3,
  label: "Interns",
  sublabel: null,
  effect: "deny",
  note: "summer",
  created_at: "2026-10-04T08:00:00",
  created_by: "admin",
  ...over,
});

function overview(chatRules: unknown[] = [], projectRules: unknown[] = []) {
  const count = (rules: unknown[], effect: string) =>
    rules.filter((r) => (r as { effect: string }).effect === effect).length;
  return {
    features: [
      { key: "chat", title: "Chat", rules: chatRules, deny_count: count(chatRules, "deny"), allow_count: count(chatRules, "allow") },
      {
        key: "projects",
        title: "Projects",
        rules: projectRules,
        deny_count: count(projectRules, "deny"),
        allow_count: count(projectRules, "allow"),
      },
    ],
  };
}

let host: HTMLDivElement;
let root: Root;
let calls: { path: string; init?: RequestInit }[];

function serve(routes: Record<string, unknown>) {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const key = Object.keys(routes).find((prefix) => path === prefix || path.startsWith(`${prefix}?`)) ?? path;
    if (!(key in routes)) throw new Error(`unexpected ${path}`);
    return routes[key] as never;
  });
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  readOnly.value = false;
  calls = [];
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
        <FeatureAccess />
      </MemoryRouter>,
    );
  });
}

function button(text: string): HTMLButtonElement {
  const found = [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === text);
  if (!found) throw new Error(`no button ${text}`);
  return found as HTMLButtonElement;
}

describe("the Feature Access page", () => {
  it("shows both sections open when there are no rules", async () => {
    serve({ "/api/admin/feature-access": overview() });
    await render();
    expect(host.querySelector("h1")?.textContent).toBe("Feature Access");
    expect(host.textContent).toContain("No rules: Chat is open to everyone.");
    expect(host.textContent).toContain("No rules: Projects is open to everyone.");
  });

  it("lists rules with who, access, note and who added them", async () => {
    serve({
      "/api/admin/feature-access": overview(
        [rule(), rule({ id: 8, target_type: "user", label: "Sara", sublabel: "sara@x", effect: "allow", note: null })],
      ),
    });
    await render();
    const rows = host.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Interns");
    expect(rows[0].textContent).toContain("Group");
    expect(rows[0].textContent).toContain("Denied");
    expect(rows[0].textContent).toContain("summer");
    expect(rows[1].textContent).toContain("Sara");
    expect(rows[1].textContent).toContain("Allowed");
  });

  it("adds a department rule", async () => {
    serve({
      "/api/admin/feature-access": overview(),
      "/api/admin/feature-access/options": { groups: [], departments: [{ name: "Sales", user_count: 4 }] },
      "/api/admin/feature-access/rules": rule({ target_type: "department", label: "Sales", feature: "projects" }),
    });
    await render();
    await act(async () => {
      [...host.querySelectorAll("button")].filter((b) => b.textContent === "Add rule")[1].click();
    });
    const kind = document.getElementById("feature-access-target-type") as HTMLSelectElement;
    await act(async () => {
      kind.value = "department";
      kind.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const department = document.getElementById("feature-access-department") as HTMLSelectElement;
    expect(department.textContent).toContain("Sales (4 users)");
    // Allow is for one person only.
    const allow = document.querySelector<HTMLInputElement>("input[value=allow]");
    expect(allow?.disabled).toBe(true);
    await act(async () => {
      department.value = "Sales";
      department.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      button("Save rule").click();
    });
    const post = calls.find((c) => c.path === "/api/admin/feature-access/rules");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      feature: "projects",
      target_type: "department",
      target: "Sales",
      effect: "deny",
      note: null,
    });
    expect(host.textContent).toContain("Projects: denied for Sales.");
  });

  it("removes a rule after asking", async () => {
    serve({
      "/api/admin/feature-access": overview([rule()]),
      "/api/admin/feature-access/rules/7": { ok: true },
    });
    await render();
    await act(async () => {
      button("Remove").click();
    });
    expect(document.body.textContent).toContain("Remove the rule that denies Chat for");
    const confirm = [...document.body.querySelectorAll("button.btn-danger")][0] as HTMLButtonElement;
    await act(async () => {
      confirm.click();
    });
    expect(calls.some((c) => c.path === "/api/admin/feature-access/rules/7" && c.init?.method === "DELETE")).toBe(true);
    expect(host.textContent).toContain("Rule for Interns removed.");
  });

  it("offers no changes to a read-only administrator", async () => {
    readOnly.value = true;
    serve({ "/api/admin/feature-access": overview([rule()]) });
    await render();
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Add rule")).toBe(false);
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Remove")).toBe(false);
  });
});

describe("its wording", () => {
  it("summarizes a section", () => {
    expect(featureSummary({ deny_count: 0, allow_count: 0 })).toBe("Open to everyone.");
    expect(featureSummary({ deny_count: 2, allow_count: 1 })).toBe(
      "Open to everyone else. Denied by 2 rules, given back to 1 person.",
    );
  });

  it("says why a person gets what they get", () => {
    expect(decisionText({ reason: "admin", via: null })).toBe("Administrators always have access.");
    expect(decisionText({ reason: "group_deny", via: "Interns" })).toBe("Denied for the group “Interns”.");
    expect(decisionText({ reason: "department_deny", via: "Sales" })).toBe("Denied for the department “Sales”.");
    expect(decisionText({ reason: "default", via: null })).toBe("No rule applies.");
  });
});
