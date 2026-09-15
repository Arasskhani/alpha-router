import { describe, expect, it, vi, afterEach } from "vitest";

vi.mock("../api", () => ({
  getCachedSession: vi.fn(),
  authFetch: vi.fn(),
  clearCachedSession: vi.fn(),
}));
vi.mock("./privateMediaStore", () => ({ clearPrivateMediaStore: vi.fn() }));

import { getCachedSession as realGetCachedSession, type SessionInfo } from "../api";
import { isPlatformFeatureEnabled } from "./session";

const getCachedSession = vi.mocked(realGetCachedSession);

function session(extra: Record<string, unknown>): SessionInfo {
  return { username: "u", role: "user", is_active: true, auth_provider: "local", ...extra };
}

afterEach(() => getCachedSession.mockReset());

describe("isPlatformFeatureEnabled", () => {
  it("is off only when the server says so", () => {
    getCachedSession.mockReturnValue(session({ features: { agents_platform: false } }));
    expect(isPlatformFeatureEnabled("agents_platform")).toBe(false);
  });

  it("is on when the server enables it", () => {
    getCachedSession.mockReturnValue(session({ features: { agents_platform: true } }));
    expect(isPlatformFeatureEnabled("agents_platform")).toBe(true);
  });

  it("is on when the server does not report features at all (older backend)", () => {
    getCachedSession.mockReturnValue(session({}));
    expect(isPlatformFeatureEnabled("agents_platform")).toBe(true);
    getCachedSession.mockReturnValue(null);
    expect(isPlatformFeatureEnabled("agents_platform")).toBe(true);
  });
});
