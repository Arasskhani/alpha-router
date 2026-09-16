import { api } from "../api";
import { showToast } from "./toastHost";

/**
 * Tell the user when their monthly budget is running down.
 *
 * The server decides *whether* there is something to say; this module decides
 * how it looks and, crucially, tells the server once it has actually been put
 * on screen. Nothing is marked as shown until then, so a warning survives a
 * closed tab or a dropped chat stream and simply reappears on the next load.
 */

type BudgetNotice = {
  level: number;
  percent: number;
  monthly_budget_usd: number;
  used_usd: number;
  remaining_usd: number;
};

type BudgetResponse = {
  monthly_budget_usd: number;
  used_usd: number;
  reserved_usd: number;
  remaining_usd: number | null;
  budget_notice?: BudgetNotice | null;
};

/**
 * Levels already shown in this tab. The server-side record is authoritative
 * across sessions; this only stops the same warning appearing twice before the
 * acknowledgement has landed — two checks racing on page load, say, or a chat
 * reply settling while the profile menu is open.
 */
const shownLevels = new Set<number>();

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

function isBudgetNotice(value: unknown): value is BudgetNotice {
  if (!value || typeof value !== "object") return false;
  const level = (value as { level?: unknown }).level;
  return typeof level === "number" && Number.isFinite(level) && level > 0;
}

/** Render a notice and acknowledge it. Safe to call with anything. */
export function presentBudgetNotice(notice: unknown): void {
  if (!isBudgetNotice(notice)) return;
  const level = Math.round(notice.level);
  if (shownLevels.has(level)) return;
  shownLevels.add(level);

  const percent = Math.round(notice.percent);
  showToast({
    eyebrow: "Budget",
    title: `You have used ${percent}% of your monthly budget.`,
    detail: `${money(notice.used_usd)} of ${money(notice.monthly_budget_usd)} used · ${money(
      notice.remaining_usd,
    )} left this month.`,
    // 90% is the last warning before requests start being refused, so it is
    // held longer and coloured accordingly.
    tone: level >= 90 ? "danger" : "warning",
    ttlMs: level >= 90 ? 9000 : 6500,
    dedupeKey: `budget-notice::${level}`,
  });

  void api("/api/user/budget/notice-ack", {
    method: "POST",
    body: JSON.stringify({ level }),
  }).catch(() => {
    // The acknowledgement is an optimisation, not a correctness requirement:
    // if it never lands the server reports the notice again next time, and the
    // in-tab guard above stops it repeating in the meantime.
  });
}

/**
 * Ask the server whether anything is outstanding.
 *
 * This — not the chat stream — is the authority. Image, video and speech spend
 * never passes through a chat turn, so a user who only generates media would
 * otherwise never hear anything at all.
 */
export async function checkBudgetNotice(): Promise<void> {
  try {
    const data = await api<BudgetResponse>("/api/user/budget");
    if (isBudgetNotice(data?.budget_notice)) {
      presentBudgetNotice(data.budget_notice);
      return;
    }
    // Nothing outstanding. That is also what the server says once a plan has
    // been raised or an administrator has reset the period, so this is where
    // the in-tab guard is released: without it, a tab left open across a reset
    // would swallow the warnings when usage climbed back.
    shownLevels.clear();
  } catch {
    /* budget state is advisory here — never surface a failure to fetch it */
  }
}

/** Test seam. */
export function resetBudgetNoticeState(): void {
  shownLevels.clear();
}
