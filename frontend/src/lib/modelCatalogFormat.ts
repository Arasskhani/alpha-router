import type { CatalogModel } from "./modelCatalog";
import { formatLocalDate } from "./dateTime";

export function formatModelTitle(m: CatalogModel): string {
  if (m.title && m.title !== m.external_id) return m.title;
  if (m.display_name && m.display_name !== m.external_id) return m.display_name;
  const parts = m.external_id.split("/");
  if (parts.length >= 2) {
    const author = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    return `${author}: ${parts.slice(1).join("/")}`;
  }
  return m.external_id;
}

export function formatContextLength(tokens: number): string {
  if (tokens >= 1_000_000) {
    const m = tokens / 1_000_000;
    return `${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)}M context`;
  }
  if (tokens >= 1000) {
    const k = tokens / 1000;
    return `${k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)}K context`;
  }
  return `${tokens.toLocaleString()} context`;
}

export function formatPerMTokenPrice(per1k: number, kind: "input" | "output"): string {
  const perM = per1k * 1000;
  const label = kind === "input" ? "input" : "output";
  if (perM >= 1) return `$${perM.toFixed(2)}/M ${label} tokens`;
  if (perM >= 0.01) return `$${perM.toFixed(2)}/M ${label} tokens`;
  return `$${perM.toFixed(4)}/M ${label} tokens`;
}

export function formatReleasedDate(iso: string): string {
  return formatLocalDate(iso);
}
