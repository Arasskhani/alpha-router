import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { formatBreakdownValue } from "./formatters";
import ModelCoinIcon from "./ModelCoinIcon";
import type { MetricKind, SegmentMeta } from "./types";

type Props = {
  models: SegmentMeta[];
  showExplore?: boolean;
};

export default function ActivityTopModels({ models, showExplore = true }: Props) {
  const [metric, setMetric] = useState<MetricKind>("tokens");

  const ranked = useMemo(() => {
    return [...models]
      .map((m) => ({ ...m, value: m[metric] as number }))
      .filter((m) => m.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);
  }, [models, metric]);

  return (
    <article className="activity-top-models card">
      <header className="activity-top-models__head">
        <h3>Top Models</h3>
        <div className="activity-top-models__actions">
          <select
            className="activity-select activity-select--sm"
            value={metric}
            onChange={(e) => setMetric(e.target.value as MetricKind)}
            aria-label="Top models metric"
          >
            <option value="tokens">Tokens</option>
            <option value="requests">Requests</option>
            <option value="spend">Spend</option>
          </select>
          {showExplore ? (
            <Link to="/admin/models" className="activity-top-models__explore">
              Explore
            </Link>
          ) : null}
        </div>
      </header>
      <ul className="activity-top-models__list">
        {ranked.map((m, idx) => (
          <li key={m.key}>
            <span className="activity-top-models__rank">{idx + 1}</span>
            <ModelCoinIcon title={m.label} />
            <span className="activity-top-models__name">{m.label}</span>
            <span className="activity-top-models__value">{formatBreakdownValue(metric, m.value)}</span>
          </li>
        ))}
        {ranked.length === 0 ? <li className="activity-legend-empty">No model usage in this period</li> : null}
      </ul>
    </article>
  );
}
