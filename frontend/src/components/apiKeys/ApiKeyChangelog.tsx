import { useEffect, useState } from "react";
import { api } from "../../api";
import { formatLocalDateTime } from "../../lib/dateTime";

type ChangeRow = {
  field: string;
  label?: string;
  old?: unknown;
  new?: unknown;
};

type ChangelogEntry = {
  id: number;
  action: string;
  created_at: string | null;
  actor: {
    id: number;
    username: string;
    email: string;
    display_name: string | null;
  } | null;
  changes: ChangeRow[];
};

function formatWhen(iso: string | null) {
  return formatLocalDateTime(iso);
}

function actorLabel(actor: ChangelogEntry["actor"]) {
  if (!actor) return "System";
  return actor.display_name || actor.username || actor.email || `User #${actor.id}`;
}

function actionLabel(action: string) {
  const map: Record<string, string> = {
    created: "Created",
    updated: "Updated",
    enabled: "Enabled",
    disabled: "Disabled",
  };
  return map[action] || action;
}

function formatValue(v: unknown) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) {
    return formatLocalDateTime(s);
  }
  return s;
}

type Props = {
  keyId: number;
};

export default function ApiKeyChangelog({ keyId }: Props) {
  const [items, setItems] = useState<ChangelogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    if (!Number.isFinite(keyId)) return;
    setLoading(true);
    const qs = new URLSearchParams();
    if (dateFrom) qs.set("from", dateFrom);
    if (dateTo) qs.set("to", dateTo);
    const suffix = qs.toString() ? `?${qs}` : "";
    api<{ items: ChangelogEntry[] }>(`/api/admin/api-keys/${keyId}/changelog${suffix}`)
      .then((d) => setItems(d.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [keyId, dateFrom, dateTo]);

  return (
    <section className="card api-key-changelog">
      <h2 className="api-key-changelog__title">Change log</h2>
      <p className="muted-text api-key-changelog__lead">
        Creation and edits to this gateway key (who changed what).
      </p>

      <div className="api-key-changelog__filters">
        <label className="api-key-changelog__filter">
          <span className="api-key-changelog__filter-label">From date</span>
          <input
            type="date"
            className="input-block"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label className="api-key-changelog__filter">
          <span className="api-key-changelog__filter-label">To date</span>
          <input
            type="date"
            className="input-block"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <div className="api-key-changelog__filter api-key-changelog__filter--action">
          <span className="api-key-changelog__filter-label api-key-changelog__filter-label--spacer" aria-hidden="true">
            &nbsp;
          </span>
          <button
            type="button"
            className="btn btn-ghost api-key-changelog__clear"
            disabled={!dateFrom && !dateTo}
            onClick={() => {
              setDateFrom("");
              setDateTo("");
            }}
          >
            Clear dates
          </button>
        </div>
      </div>

      {loading && <p className="muted-text">Loading change log…</p>}
      {!loading && items.length === 0 && (
        <p className="muted-text">
          {dateFrom || dateTo ? "No changes in this date range." : "No changes recorded yet."}
        </p>
      )}
      {!loading && items.length > 0 && (
        <p className="muted-text api-key-changelog__count">
          {items.length} entr{items.length === 1 ? "y" : "ies"}
        </p>
      )}
      <ul className="api-key-changelog__list">
        {items.map((entry) => (
          <li key={entry.id} className="api-key-changelog__entry">
            <div className="api-key-changelog__head">
              <strong>{actionLabel(entry.action)}</strong>
              <span className="muted-text">{formatWhen(entry.created_at)}</span>
            </div>
            <p className="api-key-changelog__actor muted-text">By {actorLabel(entry.actor)}</p>
            {entry.changes.length > 0 ? (
              <ul className="api-key-changelog__changes">
                {entry.changes.map((c) => (
                  <li key={`${entry.id}-${c.field}`}>
                    <span className="api-key-changelog__field">{c.label || c.field}</span>
                    {entry.action === "created" ? (
                      <span> → {formatValue(c.new)}</span>
                    ) : (
                      <span>
                        : {formatValue(c.old)} → {formatValue(c.new)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
