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
let readOnly = false;
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly }));
const confirmMock = vi.fn();
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: confirmMock, prompt: vi.fn() }) }));
// The settings card has its own page-level tests; here it only has to mount.
vi.mock("../../components/admin/ExtensionSettingsCard", () => ({ default: () => <div>settings card</div> }));

import { api } from "../../api";
import BrowserExtension from "./BrowserExtension";

const OVERVIEW = {
  enabled: true,
  full_control: false,
  package_version: "1.0.0.3",
  browsers: { connected: 4, outdated: 1, unknown_version: 0 },
  today: { agent_runs: 7, actions_refused: 2 },
  stop_runs_before: null,
};

const OVERVIEW_PATH = "/api/admin/extension/overview";

let container: HTMLDivElement;
let root: Root;

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <BrowserExtension />
      </MemoryRouter>,
    );
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`no button "${label}"; saw ${[...container.querySelectorAll("button")].map((b) => b.textContent).join(", ")}`);
  return found as HTMLButtonElement;
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  confirmMock.mockReset();
  readOnly = false;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("the Browser Extension page", () => {
  it("shows what is happening right now", async () => {
    vi.mocked(api).mockResolvedValue(OVERVIEW);
    await render();
    const text = container.textContent ?? "";
    expect(text).toContain("Connected browsers");
    expect(text).toContain("4");
    expect(text).toContain("1 on an older package");
    expect(text).toContain("Agent runs today");
    expect(text).toContain("1.0.0.3");
    // Who may use it stays on Chat Tools, and the page says so.
    expect(container.querySelector('a[href="/admin/chat-tools"]')).not.toBeNull();
    expect(text).toContain("settings card");
  });

  it("says when browsers have not reported a package", async () => {
    vi.mocked(api).mockResolvedValue({ ...OVERVIEW, browsers: { connected: 2, outdated: 0, unknown_version: 2 } });
    await render();
    expect(container.textContent).toContain("2 have not said which package");
  });

  it("stops the runs only after the administrator confirms, then says so", async () => {
    vi.mocked(api).mockResolvedValue(OVERVIEW);
    await render();
    confirmMock.mockResolvedValue(false);
    await act(async () => button("Stop all agent runs now").click());
    expect(vi.mocked(api).mock.calls.filter(([path]) => String(path).includes("stop-runs"))).toHaveLength(0);

    confirmMock.mockResolvedValue(true);
    vi.mocked(api).mockImplementation(async (path: string) =>
      path.includes("stop-runs") ? { stop_runs_before: "2026-09-27T09:00:00+00:00" } : OVERVIEW,
    );
    await act(async () => button("Stop all agent runs now").click());
    expect(vi.mocked(api).mock.calls.some(([path, init]) => String(path).includes("stop-runs") && (init as RequestInit)?.method === "POST")).toBe(true);
    expect(container.textContent).toContain("stop at its next step");
  });

  it("disconnects every browser and counts them", async () => {
    vi.mocked(api).mockResolvedValue(OVERVIEW);
    await render();
    confirmMock.mockResolvedValue(true);
    vi.mocked(api).mockImplementation(async (path: string) =>
      path.includes("disconnect-all") ? { disconnected: 3 } : OVERVIEW,
    );
    await act(async () => button("Disconnect all browsers").click());
    expect(container.textContent).toContain("3 browsers were disconnected.");
  });

  it("tells the administrator when a stop is standing", async () => {
    vi.mocked(api).mockResolvedValue({ ...OVERVIEW, stop_runs_before: "2026-09-27T09:00:00+00:00" });
    await render();
    expect(container.textContent).toContain("were stopped");
  });

  it("lets a read-only administrator look but offers no buttons", async () => {
    readOnly = true;
    vi.mocked(api).mockResolvedValue(OVERVIEW);
    await render();
    expect(container.textContent).toContain("Connected browsers");
    expect([...container.querySelectorAll("button")].map((b) => b.textContent)).not.toContain("Stop all agent runs now");
  });

  it("reports a failed load", async () => {
    vi.mocked(api).mockRejectedValue(new Error("nope"));
    await render();
    expect(container.querySelector(".alert-error")?.textContent).toContain("nope");
  });

  it("asks the server for the overview once", async () => {
    vi.mocked(api).mockResolvedValue(OVERVIEW);
    await render();
    expect(vi.mocked(api).mock.calls.filter(([path]) => path === OVERVIEW_PATH)).toHaveLength(1);
  });
});
