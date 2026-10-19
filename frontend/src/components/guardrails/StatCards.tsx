import type { Overview } from "../../lib/guardrails";

function detail(overview: Overview, action: string): string {
  const top = overview.top_by_action[action] ?? [];
  return top.map((t) => `${t.name} ${t.count}`).join(" · ");
}

/** The last seven days at a glance: blocked, masked, routed and only monitored. */
export default function StatCards({ overview }: { overview: Overview | null }) {
  if (!overview) return null;
  const totals = overview.totals_7d;
  const cards = [
    { key: "block", label: "Blocked · last 7 days", value: totals.block, tone: "block" },
    { key: "redact", label: "Redacted · last 7 days", value: totals.redact, tone: "redact" },
    { key: "route", label: "Routed · last 7 days", value: totals.route, tone: "route" },
    { key: "monitor", label: "Monitored only · last 7 days", value: totals.monitor, tone: "monitor" },
  ];
  return (
    <div className="guardrails-stats">
      {cards.map((card) => (
        <div key={card.key} className="card guardrails-stat" data-testid={`guardrails-stat-${card.key}`}>
          <span className="guardrails-stat__label">{card.label}</span>
          <span className={`guardrails-stat__value guardrails-tone--${card.tone}`}>{card.value}</span>
          <span className="guardrails-stat__detail">
            {card.key === "monitor" && overview.rules.monitor
              ? `${overview.rules.monitor} ${overview.rules.monitor === 1 ? "rule" : "rules"} not yet enforcing`
              : detail(overview, card.key) || "—"}
          </span>
        </div>
      ))}
    </div>
  );
}
