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
import { decisionText, featureNote, featureSummary } from "../../lib/featureAccess";
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
    expect(host.querySelectorAll(".settings-section-desc")[0]?.textContent).toBe("Open to everyone.");
    expect(host.querySelectorAll(".settings-section-desc")[1]?.textContent).toBe("Open to everyone.");
    expect(host.textContent).toContain("No rules yet.");
  });

  it("draws every section the server governs, with what each also covers", async () => {
    const data = overview();
    data.features.splice(2, 0, {
      key: "project_create",
      title: "Create projects",
      rules: [],
      deny_count: 0,
      allow_count: 0,
    });
    data.features.push({ key: "api_keys", title: "API keys", rules: [], deny_count: 0, allow_count: 0 });
    data.features.push({ key: "extension", title: "Browser extension", rules: [], deny_count: 0, allow_count: 0 });
    serve({ "/api/admin/feature-access": data });
    await render();
    expect([...host.querySelectorAll("h2")].map((h) => h.textContent)).toEqual([
      "Chat",
      "Projects",
      "Create projects",
      "API keys",
      "Browser extension",
      "Check a user",
    ]);
    const createSection = host.querySelector('[aria-labelledby="feature-access-project_create"]');
    expect(createSection?.querySelector(".form-hint")?.textContent).toContain("Closed whenever Projects is");
    const projectsSection = host.querySelector('[aria-labelledby="feature-access-projects"]');
    expect(projectsSection?.querySelector(".form-hint")).toBeNull();
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

describe("adding for a user or a group, and checking a person", () => {
  it("offers Allow for a user and not for a group", async () => {
    serve({
      "/api/admin/feature-access": overview(),
      "/api/admin/feature-access/options": { groups: [{ id: 3, name: "Interns", source: "local", member_count: 2 }], departments: [] },
      "/api/admin/feature-access/user-options": [],
    });
    await render();
    await act(async () => {
      [...host.querySelectorAll("button")].filter((b) => b.textContent === "Add rule")[0].click();
    });
    expect(document.querySelector<HTMLInputElement>("input[value=allow]")?.disabled).toBe(false);
    const kind = document.getElementById("feature-access-target-type") as HTMLSelectElement;
    await act(async () => {
      kind.value = "group";
      kind.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(document.getElementById("feature-access-group")?.textContent).toContain("Interns (2 members)");
    expect(document.querySelector<HTMLInputElement>("input[value=allow]")?.disabled).toBe(true);
    expect(document.body.textContent).toContain("saving replaces it");
  });

  it("shows what a picked person gets and why", async () => {
    serve({
      "/api/admin/feature-access": overview([rule()]),
      "/api/admin/feature-access/user-options": [{ id: 5, username: "sara", email: "sara@x", display_name: "Sara" }],
      "/api/admin/feature-access/check": {
        user: { id: 5, label: "Sara", department: null },
        features: [
          { feature: "chat", title: "Chat", allowed: false, reason: "group_deny", rule_id: 7, via: "Interns" },
          { feature: "projects", title: "Projects", allowed: true, reason: "default", rule_id: null, via: null },
        ],
      },
    });
    await render();
    const input = document.getElementById("feature-access-check-user") as HTMLInputElement;
    await act(async () => {
      input.focus();
      input.dispatchEvent(new FocusEvent("focus"));
    });
    await act(async () => {
      await new Promise((done) => setTimeout(done, 250));
    });
    const option = [...document.querySelectorAll<HTMLButtonElement>(".user-owner-select__item")][0];
    await act(async () => {
      option.click();
    });
    const result = host.querySelector(".feature-access-check");
    expect(result?.textContent).toContain("Closed");
    expect(result?.textContent).toContain("Denied for the group “Interns”.");
    expect(calls.some((c) => c.path === "/api/admin/feature-access/check?user_id=5")).toBe(true);
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
    expect(decisionText({ reason: "projects_closed", via: null })).toBe(
      "Closed because Projects is closed for this person.",
    );
    expect(decisionText({ reason: "chat_closed", via: "Sales" })).toBe(
      "Closed because Chat is closed for this person. An Allow here gives it back.",
    );
  });

  it("explains what closes with what", () => {
    expect(featureNote("chat")).toContain("also closes Create projects");
    expect(featureNote("project_create")).toContain("Closed whenever Projects is");
    expect(featureNote("extension")).toContain("Chat Tools applies on top");
    expect(featureNote("projects")).toBe("");
  });
});
