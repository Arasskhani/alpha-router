/**
 * @vitest-environment happy-dom
 *
 * Feature Access → Create projects: closed (or closed with Chat), the Projects
 * page offers no way to create one and says why, and the projects the person
 * is in are still listed.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ value: { features: {} as Record<string, boolean> } }));
vi.mock("../hooks/useCachedSession", () => ({ useCachedSession: () => session.value }));
vi.mock("../lib/projectsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/projectsApi")>()),
  listProjects: vi.fn(async (scope: string) => ({
    projects:
      scope === "mine"
        ? [{ id: "p1", name: "Team", status: "active", visibility: "private", revision: 1, aclVersion: 1, myRole: "contributor", isMember: true }]
        : [],
    total: scope === "mine" ? 1 : 0,
  })),
}));

import ProjectsPage from "./Projects";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  session.value = { features: {} };
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
        <ProjectsPage />
      </MemoryRouter>,
    );
  });
}

function newProjectButton() {
  return [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("New project"));
}

describe("the Projects page", () => {
  it("offers New project when creating is open (or the server does not say)", async () => {
    await render();
    expect(newProjectButton()).toBeDefined();
    expect(host.textContent).not.toContain("Creating projects isn't enabled");
  });

  it("offers no way to create one when Create projects is closed, and says why", async () => {
    session.value = { features: { project_create: false } };
    await render();
    expect(newProjectButton()).toBeUndefined();
    expect(host.querySelector('[role="status"]')?.textContent).toBe(
      "Creating projects isn't enabled for your account. You can still work in projects you're invited to.",
    );
    expect(host.querySelector(".project-card-name")?.textContent).toBe("Team");
  });
});
