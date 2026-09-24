/**
 * @vitest-environment happy-dom
 *
 * "/" sends a signed-in user to their home page and anyone else to sign in.
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({ role: null as string | null }));

vi.mock("../api", () => ({
  bootstrapSession: () =>
    server.role ? Promise.resolve({ role: server.role }) : Promise.reject(new Error("Not authenticated")),
}));

import HomeRedirect from "./HomeRedirect";

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

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

async function openRoot(): Promise<string> {
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );
  });
  // Let the session promise settle and the redirect render.
  await act(async () => {
    await Promise.resolve();
  });
  return host.querySelector("[data-testid=where]")?.textContent ?? "(no redirect)";
}

describe("HomeRedirect", () => {
  it("sends a user to chat", async () => {
    server.role = "user";
    expect(await openRoot()).toBe("/app/chat");
  });

  it("sends an admin-panel role to the first admin page it may open, as sign-in does", async () => {
    server.role = "super_admin";
    const where = await openRoot();
    expect(where.startsWith("/admin")).toBe(true);
  });

  it("sends someone who is not signed in to the sign-in page", async () => {
    server.role = null;
    expect(await openRoot()).toBe("/login");
  });
});
