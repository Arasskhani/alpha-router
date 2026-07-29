import { useMemo, useState } from "react";
import ModelName from "../../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../../formatters";
import type { ActivityExplore, ExploreMetric } from "../../types";

type SortKey = "label" | "min" | "max" | "avg" | "sum" | "value" | "pct";

type Props = {
  explore: ActivityExplore;
};

function formatCell(metric: ExploreMetric, v: number): string {
  if (metric === "total_usage") return formatSpend(v);
  if (metric === "request_count") return formatRequests(v);
  if (metric === "avg_latency" || metric === "p50_latency") {
    if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
    return `${Math.round(v)}ms`;
  }
  return formatTokens(v);
}

export default function ExploreTable({ explore }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => {
    const copy = [...explore.table];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") {
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return asc ? Number(av) - Number(bv) : Number(bv) - Number(av);
    });
    return copy;
  }, [explore.table, sortKey, asc]);

  function toggle(key: SortKey) {
    if (sortKey === key) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(key === "label");
    }
  }

  const entityHeader =
    explore.group === "none" ? "Entity" : explore.group.charAt(0).toUpperCase() + explore.group.slice(1).replace("_", " ");

  return (
    <div className="explore-table card">
      <div className="explore-table__scroll">
        <table>
          <thead>
            <tr>
              {(
                [
                  ["label", entityHeader],
                  ["min", "Min"],
                  ["max", "Max"],
                  ["avg", "Avg"],
                  ["sum", "Sum"],
                  ["value", "Value"],
                  ["pct", "% of Total"],
                ] as [SortKey, string][]
              ).map(([key, title]) => (
                <th key={key}>
                  <button type="button" className="explore-table__sort" onClick={() => toggle(key)}>
                    {title}
                    <span className="explore-table__arrows" aria-hidden>
                      {sortKey === key ? (asc ? "↑" : "↓") : "↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <span className="explore-table__entity">
                    <span className="overview-chart-card__dot" style={{ background: row.color }} />
                    <ModelName
                      modelId={row.key.includes("›") ? row.key.split("›")[0] : row.key}
                      label={row.label}
                      showIcon={
                        (explore.group === "model" || explore.group === "provider") &&
                        row.key !== "__others__" &&
                        !row.key.startsWith("__")
                      }
                      size={15}
                    />
                  </span>
                </td>
                <td>{formatCell(explore.metric, row.min)}</td>
                <td>{formatCell(explore.metric, row.max)}</td>
                <td>{formatCell(explore.metric, row.avg)}</td>
                <td>{formatCell(explore.metric, row.sum)}</td>
                <td>{formatCell(explore.metric, row.value)}</td>
                <td>
                  <span className="explore-table__pct">
                    <span className="explore-table__bar-track">
                      <span
                        className="explore-table__bar"
                        style={{ width: `${Math.min(100, Math.max(0, row.pct))}%`, background: row.color }}
                      />
                    </span>
                    <span>{row.pct.toFixed(1)}%</span>
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted-text">
                  No rows in this period
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="explore-table__footer muted-text">
        {explore.meta.row_count} rows · {explore.meta.entity_count} shown
      </p>
    </div>
  );
}
