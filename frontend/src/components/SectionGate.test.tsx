/**
 * @vitest-environment happy-dom
 *
 * A section Feature Access closed shows why, instead of a page that fails on every request.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({ features: {} as Record<string, boolean> }));

vi.mock("../api", () => ({
  getCachedSession: () => ({ role: "user", features: server.features }),
  onSessionReady: () => () => undefined,
}));

import SectionGate from "./SectionGate";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function open(section: "chat" | "projects") {
  act(() => {
    root.render(
      <MemoryRouter>
        <SectionGate section={section}>
          <p data-testid="page">the page</p>
        </SectionGate>
      </MemoryRouter>,
    );
  });
}

describe("SectionGate", () => {
  it("shows the page when the section is open", () => {
    server.features = {};
    open("chat");
    expect(host.querySelector("[data-testid=page]")).not.toBeNull();
  });

  it("explains a closed Chat and points to Projects", () => {
    server.features = { chat: false };
    open("chat");
    expect(host.querySelector("[data-testid=page]")).toBeNull();
    expect(host.querySelector("h1")?.textContent).toBe("Chat isn't enabled for you");
    expect(host.textContent).toContain("Your project chats still work in Projects.");
    expect(host.querySelector("a")?.getAttribute("href")).toBe("/app/projects");
  });

  it("explains closed Projects and points to Chat", () => {
    server.features = { projects: false };
    open("projects");
    expect(host.querySelector("h1")?.textContent).toBe("Projects isn't enabled for you");
    expect(host.querySelector("a")?.getAttribute("href")).toBe("/app/chat");
  });
});
