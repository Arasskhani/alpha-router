import { ACTION_LABELS, type Overview } from "../../lib/guardrails";
import StatCards from "./StatCards";

const CHANNEL_LABELS: Record<string, string> = {
  chat: "Chat",
  attachments: "Attachments",
  context: "Context",
  extension: "Extension",
  gateway: "Gateway",
  web_search: "Web search",
  web_fetch: "Web fetch",
};

/** The last 30 days: a stacked bar per day, then the rules and channels that matched most. */
export default function OverviewTab({ overview }: { overview: Overview | null }) {
  if (!overview) return <p className="muted-text">Loading…</p>;
  const max = Math.max(1, ...overview.daily.map((d) => d.block + d.redact + d.route + d.monitor));
  const totalChannels = overview.by_channel.reduce((sum, c) => sum + c.count, 0) || 1;
  return (
    <div className="guardrails-overview">
      <StatCards overview={overview} />
      <div className="card guardrails-chart">
        <h3>Last 30 days</h3>
        <div className="guardrails-bars" role="img" aria-label="Events per day over the last 30 days">
          {overview.daily.map((day) => {
            const total = day.block + day.redact + day.route + day.monitor;
            return (
              <div key={day.date} className="guardrails-bar" title={`${day.date}: ${total} events`}>
                {(["monitor", "redact", "route", "block"] as const).map((action) =>
                  day[action] ? (
                    <span
                      key={action}
                      className={`guardrails-bar__part guardrails-bg--${action}`}
                      style={{ height: `${(day[action] / max) * 100}%` }}
                    />
                  ) : null,
                )}
              </div>
            );
          })}
        </div>
        <div className="guardrails-legend">
          {(["block", "redact", "route", "monitor"] as const).map((action) => (
            <span key={action}>
              <span className={`guardrails-swatch guardrails-bg--${action}`} aria-hidden /> {ACTION_LABELS[action]}
            </span>
          ))}
        </div>
      </div>
      <div className="guardrails-columns">
        <div className="card">
          <h3>Top rules · 7 days</h3>
          {overview.top_rules.length ? (
            <ol className="guardrails-list">
              {overview.top_rules.map((rule) => (
                <li key={rule.rule_id}>
                  <span>{rule.name}</span>
                  <strong>{rule.count}</strong>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted-text">No rule has matched in the last 7 days.</p>
          )}
        </div>
        <div className="card">
          <h3>By channel · 7 days</h3>
          {overview.by_channel.length ? (
            <ul className="guardrails-list">
              {overview.by_channel.map((row) => (
                <li key={row.channel}>
                  <span>{CHANNEL_LABELS[row.channel] ?? row.channel}</span>
                  <strong>{Math.round((row.count / totalChannels) * 100)}%</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted-text">Nothing yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
