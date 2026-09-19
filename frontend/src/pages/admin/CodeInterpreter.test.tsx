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
const confirmMock = vi.fn();
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: confirmMock, prompt: vi.fn() }) }));

import { api } from "../../api";
import CodeInterpreter from "./CodeInterpreter";

const settings = (over: Record<string, unknown> = {}) => ({
  policy: { enabled: true, max_concurrent_turns: 200, max_per_subject: 2, retry_after_seconds: 30 },
  workspace: { max_workspace_files: 10, max_workspace_total_mb: 10 },
  deployment: {
    hard_max_concurrent_turns: { value: 200, env: "CODE_INTERPRETER_CAPACITY_GLOBAL_MAX" },
    lease_ttl_seconds: { value: 900, env: "CODE_INTERPRETER_CAPACITY_LEASE_TTL_SECONDS" },
    heartbeat_seconds: { value: 30, env: "CODE_INTERPRETER_CAPACITY_HEARTBEAT_SECONDS" },
    execution_timeout_seconds: { value: 20, env: "CODE_SANDBOX_TIMEOUT_SECONDS" },
    broker_max_concurrent: { value: 200, env: "SANDBOX_MAX_CONCURRENT" },
  },
  effective: {
    max_concurrent_turns: 200,
    available: 200,
    utilization_percent: 0,
    limited_by: "both",
    mismatch: false,
    app_max_concurrent_turns: 200,
    broker_max_concurrent: 200,
  },
  broker: { status: "ok", active_jobs: 0 },
  ...over,
});

let container: HTMLDivElement;
let root: Root;

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <CodeInterpreter />
      </MemoryRouter>,
    );
  });
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  confirmMock.mockReset();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Code Interpreter settings page", () => {
  it("names the environment variable behind every value it cannot change", async () => {
    vi.mocked(api).mockResolvedValue(settings());
    await render();
    const text = container.textContent ?? "";
    for (const env of [
      "CODE_INTERPRETER_CAPACITY_GLOBAL_MAX",
      "CODE_INTERPRETER_CAPACITY_LEASE_TTL_SECONDS",
      "CODE_INTERPRETER_CAPACITY_HEARTBEAT_SECONDS",
      "CODE_SANDBOX_TIMEOUT_SECONDS",
      "SANDBOX_MAX_CONCURRENT",
    ]) {
      expect(text).toContain(env);
    }
  });

  it("warns when the two admission gates disagree", async () => {
    vi.mocked(api).mockResolvedValue(
      settings({
        effective: {
          max_concurrent_turns: 50,
          available: 50,
          utilization_percent: 0,
          limited_by: "broker",
          mismatch: true,
          app_max_concurrent_turns: 200,
          broker_max_concurrent: 50,
        },
      }),
    );
    await render();
    const warning = container.querySelector(".alert-warning");
    expect(warning?.textContent).toContain("SANDBOX_MAX_CONCURRENT=50");
  });

  it("says nothing about a mismatch when the gates agree", async () => {
    vi.mocked(api).mockResolvedValue(settings());
    await render();
    expect(container.querySelector(".alert-warning")).toBeNull();
  });

  it("asks before taking the feature away from everyone", async () => {
    vi.mocked(api).mockResolvedValue(settings());
    confirmMock.mockResolvedValue(false);
    await render();
    const button = [...container.querySelectorAll("button")].find((b) => b.textContent === "Turn off");
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(confirmMock).toHaveBeenCalledOnce();
    // Declined: the only calls are the initial load, never a PATCH.
    expect(vi.mocked(api).mock.calls.every(([, init]) => !init)).toBe(true);
  });

  it("does not ask when turning it back on", async () => {
    vi.mocked(api).mockResolvedValue(settings({ policy: { ...settings().policy, enabled: false } }));
    await render();
    const button = [...container.querySelectorAll("button")].find((b) => b.textContent === "Turn on");
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(vi.mocked(api).mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "PATCH")).toBe(
      true,
    );
  });

  it("every input is named by a label", async () => {
    vi.mocked(api).mockResolvedValue(settings());
    await render();
    const inputs = [...container.querySelectorAll("input")];
    expect(inputs.length).toBeGreaterThan(0);
    for (const input of inputs) {
      expect(container.querySelector(`label[for="${input.id}"]`)).not.toBeNull();
    }
  });
});
