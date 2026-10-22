/**
 * @vitest-environment happy-dom
 *
 * Retention Policy: the read-only Support tickets line. Its window is set in
 * Admin › Tickets › Settings; this page only says what it is.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn() }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: vi.fn(), prompt: vi.fn() }) }));

import { api } from "../../api";
import RetentionPolicy from "./RetentionPolicy";

const OVERVIEW = {
  total_files: 0,
  total_size_bytes: 0,
  expired_files: 0,
  settings: { retention_days: 30, clear_schedule_enabled: true, clear_schedule_hour: 3, clear_schedule_minute: 0 },
};

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

async function render(extra: Record<string, unknown>) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/admin/storage") return { ...OVERVIEW, ...extra };
    throw new Error(`unexpected ${path}`);
  });
  await act(async () => {
    root.render(
      <MemoryRouter>
        <RetentionPolicy />
      </MemoryRouter>,
    );
  });
}

describe("Retention Policy · Support tickets", () => {
  it("says after how many days closed tickets are deleted, and where that is set", async () => {
    await render({ tickets: { retention_days: 365 } });
    const line = host.querySelector('[data-testid="ticket-retention"]');
    expect(line?.textContent).toContain("Closed tickets and their images are deleted after 365 days");
    expect(line?.textContent).toContain("Admin › Tickets › Settings");
    expect(line?.querySelector("a")?.getAttribute("href")).toBe("/admin/tickets/settings");
    expect(line?.querySelector("input")).toBeNull();
  });

  it("says they are kept when the window is 0", async () => {
    await render({ tickets: { retention_days: 0 } });
    const text = host.querySelector('[data-testid="ticket-retention"]')?.textContent ?? "";
    expect(text).toContain("Closed tickets and their images are kept");
    expect(text).not.toContain("deleted after");
  });

  it("uses the singular for one day", async () => {
    await render({ tickets: { retention_days: 1 } });
    expect(host.querySelector('[data-testid="ticket-retention"]')?.textContent).toContain("deleted after 1 day (");
  });

  it("shows nothing about tickets when the server does not send the block", async () => {
    await render({});
    expect(host.querySelector('[data-testid="ticket-retention"]')).toBeNull();
  });
});
