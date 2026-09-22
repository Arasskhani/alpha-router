/**
 * @vitest-environment happy-dom
 *
 * The page's contract with the server, and the three things it must say
 * honestly: the filter it arrived with, that the export carries the same
 * filter as the list, and that a sign-out for a federated account is the
 * identity provider's record rather than a gap in ours.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  api: vi.fn(),
  authFetch: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));

import { api, authFetch } from "../../api";
import {
  EMPTY_FILTERS,
  IDP_SIGN_OUT_NOTE,
  REASON_LABELS,
  buildSignInQuery,
  outcomeBadgeClass,
  reasonLabel,
  scopeSentence,
  signInActivityPathForUser,
  signOutIsRecordedByIdp,
  userIdFromSearch,
} from "../../lib/signInActivity";
import SignInActivity from "./SignInActivity";

const EVENT = {
  id: 41,
  occurred_at: "2026-09-20T12:00:00",
  user_id: 7,
  username: "alice",
  event_type: "login_failed",
  outcome: "failure",
  scope: null,
  reason_code: "bad_password",
  reason_detail: "Invalid credentials",
  auth_method: "saml",
  ip: "203.0.113.7",
  user_agent: "Mozilla/5.0",
  session_id: null,
  correlation_id: "c-1",
  backfilled: false,
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(authFetch).mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(path = "/admin/sign-in-activity") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <SignInActivity />
      </MemoryRouter>,
    );
  });
}

function requested(): string[] {
  return vi.mocked(api).mock.calls.map((c) => String(c[0]));
}

describe("labels", () => {
  it("has a sentence for every reason code the server can store", () => {
    // Mirrors REASON_CODES in backend/app/models/auth_event.py.
    const serverCodes = [
      "bad_password",
      "no_such_user",
      "account_inactive",
      "account_deleted",
      "twofa_required",
      "twofa_failed",
      "ldap_unavailable",
      "ldap_rejected",
      "saml_rejected",
      "oidc_rejected",
      "sso_code_invalid",
      "unknown",
      "rate_limited",
      "password_changed",
      "admin_password_reset",
      "admin_2fa_disabled",
      "user_deactivated",
      "user_deleted",
    ];
    for (const code of serverCodes) expect(REASON_LABELS[code], code).toBeTruthy();
    expect(reasonLabel(null)).toBe("—");
    expect(reasonLabel("something_new")).toBe("Something new");
  });

  it("colours by outcome: green worked, red failed, grey neither", () => {
    expect(outcomeBadgeClass({ outcome: "success" })).toContain("--active");
    expect(outcomeBadgeClass({ outcome: "failure" })).toContain("--failed");
    expect(outcomeBadgeClass({ outcome: "n/a" })).toContain("--neutral");
  });

  it("describes a revocation as signed out everywhere, never as a duration", () => {
    expect(
      scopeSentence({ event_type: "session_revoked", scope: "all_sessions", reason_code: "password_changed" }),
    ).toBe("Signed out everywhere: password changed.");
    expect(scopeSentence({ event_type: "logout", scope: "all_sessions", reason_code: null })).toMatch(/every session/);
    expect(scopeSentence({ event_type: "login_success", scope: null, reason_code: null })).toBeNull();
  });

  it("refers SAML and OIDC sign-outs to the identity provider and nothing else", () => {
    expect(signOutIsRecordedByIdp("saml")).toBe(true);
    expect(signOutIsRecordedByIdp("oidc")).toBe(true);
    expect(signOutIsRecordedByIdp("local")).toBe(false);
    expect(signOutIsRecordedByIdp("ldap")).toBe(false);
    expect(signOutIsRecordedByIdp(null)).toBe(false);
  });
});

describe("the query", () => {
  it("is the same for the list and the export, paging aside", () => {
    const filters = { ...EMPTY_FILTERS, userId: "7", username: " Ali ", eventType: "login_failed", ip: "203.0.113.7" };
    const list = buildSignInQuery(filters, { limit: 100, offset: 200 });
    const file = buildSignInQuery(filters);
    expect(list.get("limit")).toBe("100");
    expect(list.get("offset")).toBe("200");
    for (const key of ["user_id", "username", "event_type", "ip"]) expect(file.get(key)).toBe(list.get(key));
    expect(file.has("limit")).toBe(false);
    expect(file.get("username")).toBe("Ali");
    expect(file.get("user_id")).toBe("7");
  });

  it("reads only a positive integer out of ?user=", () => {
    expect(userIdFromSearch(new URLSearchParams("user=42"))).toBe("42");
    expect(userIdFromSearch(new URLSearchParams("user=abc"))).toBe("");
    expect(userIdFromSearch(new URLSearchParams("user=-1"))).toBe("");
    expect(userIdFromSearch(new URLSearchParams(""))).toBe("");
    expect(signInActivityPathForUser(42)).toBe("/admin/sign-in-activity?user=42");
  });
});

describe("the way in from Users", () => {
  it("is a row action that opens the page filtered to that account", () => {
    // The Users page is too large to mount here; the wiring is a string.
    const sources = import.meta.glob("./Users.tsx", { query: "?raw", import: "default", eager: true }) as Record<
      string,
      string
    >;
    const users = sources["./Users.tsx"] ?? "";
    expect(users).toContain('label: "Sign-in activity"');
    expect(users).toContain("navigate(signInActivityPathForUser(u.id))");
  });
});

describe("the page", () => {
  it("arrives filtered to the user in the URL and says so", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path.startsWith("/api/admin/sign-in-activity?"))
        return { items: [EVENT], limit: 100, offset: 0, has_more: false };
      throw new Error(`unexpected ${path}`);
    });
    await render("/admin/sign-in-activity?user=7");

    expect(requested()[0]).toContain("user_id=7");
    const banner = host.querySelector(".alert-info");
    expect(banner?.textContent).toContain("alice");
    expect(banner?.querySelector("a")?.getAttribute("href")).toBe("/admin/users/7/activity");
  });

  it("exports with exactly the filters the list used", async () => {
    vi.mocked(api).mockResolvedValue({ items: [], limit: 100, offset: 0, has_more: false });
    const headers = new Headers({
      "Content-Disposition": 'attachment; filename="alpharouter-sign-in-activity-x.csv"',
      "X-Truncated": "true",
      "X-Row-Count": "50000",
    });
    vi.mocked(authFetch).mockResolvedValue({
      ok: true,
      status: 200,
      headers,
      blob: async () => new Blob(["\ufeffTime"]),
      json: async () => ({}),
    } as unknown as Response);
    // happy-dom lacks these two in this environment.
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => "blob:x";
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
    HTMLAnchorElement.prototype.click = () => {};

    await render("/admin/sign-in-activity?user=7");
    const exportButton = [...host.querySelectorAll("button")].find((b) => b.textContent === "Export CSV");
    await act(async () => exportButton?.click());

    const url = String(vi.mocked(authFetch).mock.calls[0][0]);
    expect(url.startsWith("/api/admin/sign-in-activity/export.csv?")).toBe(true);
    expect(url).toContain("user_id=7");
    expect(url).not.toContain("limit=");
    expect(host.querySelector(".alert-success")?.textContent).toContain("first 50,000 rows");
  });

  it("shows the identity-provider note only for federated accounts", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/admin/sign-in-activity/41") return { ...EVENT, user: null };
      if (path === "/api/admin/sign-in-activity/42") return { ...EVENT, id: 42, auth_method: "local", user: null };
      return {
        items: [EVENT, { ...EVENT, id: 42, auth_method: "local" }],
        limit: 100,
        offset: 0,
        has_more: false,
      };
    });
    await render();

    const rows = host.querySelectorAll("tbody tr");
    await act(async () => (rows[0] as HTMLElement).click());
    expect(document.body.textContent).toContain(IDP_SIGN_OUT_NOTE);
    expect(document.body.textContent).toContain("Wrong password");
    expect(document.body.textContent).toContain("Invalid credentials");

    const close = [...document.querySelectorAll("button")].find((b) =>
      /close/i.test(b.getAttribute("aria-label") || ""),
    );
    await act(async () => close?.click());
    await act(async () => (rows[1] as HTMLElement).click());
    expect(document.body.textContent).not.toContain(IDP_SIGN_OUT_NOTE);
  });
});
