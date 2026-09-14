/** Shared chat multi-model helpers (picker / topbar / selection cap). */

export const MAX_MULTI_MODELS = 4;

export function catalogMonthLabel(now = new Date()): string {
  return now.toLocaleString("en-US", { month: "long", year: "numeric" });
}
