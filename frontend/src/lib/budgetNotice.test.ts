/**
 * @vitest-environment happy-dom
 *
 * The toast host is raw DOM by design — it has to be callable from a stream
 * callback with no component to hang off — so exercising it needs a document.
 * Scoped to this file rather than switched on globally: the rest of the suite
 * is pure logic and is faster without one.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { checkBudgetNotice, presentBudgetNotice, resetBudgetNoticeState } from "./budgetNotice";
import { resetToastHost, showToast } from "./toastHost";

const acks: unknown[] = [];
let budgetResponse: unknown = { budget_notice: null };

vi.mock("../api", () => ({
  api: vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/user/budget") return budgetResponse;
    acks.push(JSON.parse(String(init?.body || "{}")));
    return {};
  }),
}));

function toasts(): HTMLElement[] {
  return Array.from(document.querySelectorAll(".app-toast"));
}

beforeEach(() => {
  vi.useFakeTimers();
  acks.length = 0;
  resetBudgetNoticeState();
  resetToastHost();
  budgetResponse = { budget_notice: null };
});

afterEach(() => {
  vi.useRealTimers();
});

const NOTICE_70 = {
  level: 70,
  percent: 72.4,
  monthly_budget_usd: 100,
  used_usd: 72.4,
  remaining_usd: 27.6,
};

describe("presentBudgetNotice", () => {
  it("shows the percentage and the figures behind it", () => {
    presentBudgetNotice(NOTICE_70);
    const [toast] = toasts();
    expect(toast).toBeTruthy();
    expect(toast.textContent).toContain("72%");
    expect(toast.textContent).toContain("$27.60 left");
  });

  it("tells the server it was shown, so it is not repeated next session", () => {
    presentBudgetNotice(NOTICE_70);
    expect(acks).toEqual([{ level: 70 }]);
  });

  it("does not repeat the same threshold in one tab", () => {
    presentBudgetNotice(NOTICE_70);
    presentBudgetNotice(NOTICE_70);
    expect(toasts()).toHaveLength(1);
    expect(acks).toHaveLength(1);
  });

  it("still speaks up at the next threshold", () => {
    presentBudgetNotice(NOTICE_70);
    presentBudgetNotice({ ...NOTICE_70, level: 90, percent: 91, remaining_usd: 9 });
    expect(toasts()).toHaveLength(2);
  });

  it("colours 90% as the last warning before requests are refused", () => {
    presentBudgetNotice({ ...NOTICE_70, level: 90, percent: 91 });
    expect(toasts()[0].className).toContain("app-toast--danger");
  });

  it("ignores anything that is not a notice", () => {
    for (const value of [undefined, null, {}, { level: 0 }, "70", { level: Number.NaN }]) {
      presentBudgetNotice(value);
    }
    expect(toasts()).toHaveLength(0);
    expect(acks).toHaveLength(0);
  });
});

describe("the shared toast host", () => {
  it("queues rather than replacing, so one message cannot erase another", () => {
    showToast({ eyebrow: "Chat ready", title: "A reply arrived" });
    presentBudgetNotice(NOTICE_70);
    expect(toasts()).toHaveLength(2);
  });

  it("drops the oldest once more than three are on screen", () => {
    for (const n of [1, 2, 3, 4]) showToast({ eyebrow: "E", title: `t${n}` });
    const visible = toasts().map((t) => t.textContent);
    expect(visible).toHaveLength(3);
    expect(visible.join(" ")).not.toContain("t1");
    expect(visible.join(" ")).toContain("t4");
  });

  it("clears a toast when its time is up", () => {
    showToast({ eyebrow: "E", title: "t", ttlMs: 1000 });
    expect(toasts()).toHaveLength(1);
    vi.advanceTimersByTime(1001);
    expect(toasts()).toHaveLength(0);
  });

  it("is a button only when there is somewhere to go", () => {
    showToast({ eyebrow: "E", title: "plain" });
    showToast({ eyebrow: "E", title: "clickable", onClick: () => {} });
    const [plain, clickable] = toasts();
    expect(plain.tagName).toBe("DIV");
    expect(clickable.tagName).toBe("BUTTON");
  });
});

describe("checkBudgetNotice", () => {
  it("releases the in-tab guard once the server has nothing outstanding", async () => {
    // A tab left open across an administrator's budget reset: the same
    // threshold must be allowed to warn again when usage climbs back.
    presentBudgetNotice(NOTICE_70);
    expect(toasts()).toHaveLength(1);

    budgetResponse = { budget_notice: null };
    await checkBudgetNotice();
    resetToastHost();

    presentBudgetNotice(NOTICE_70);
    expect(toasts()).toHaveLength(1);
  });

  it("shows whatever the server reports as outstanding", async () => {
    budgetResponse = { budget_notice: NOTICE_70 };
    await checkBudgetNotice();
    expect(toasts()).toHaveLength(1);
  });
});
