import { useCallback, useEffect, useState } from "react";

import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { GUARDRAILS_BASE, type TrustLevel } from "../../lib/guardrails";

type Destinations = {
  connections: { id: number; name: string; kind: string; provider_type: string; is_active: boolean; trust_level: TrustLevel }[];
  implicit: { key: string; label: string; kind: string; trust_level: TrustLevel }[];
};

const TRUST: { key: TrustLevel; label: string }[] = [
  { key: "internal", label: "Internal" },
  { key: "trusted", label: "Trusted external" },
  { key: "public", label: "Public" },
];

/** How far each place text is sent to may be trusted; rules name trust levels, not connections. */
export default function DestinationsTab({ onChanged }: { onChanged: () => Promise<void> | void }) {
  const readOnly = useReadOnly();
  const [data, setData] = useState<Destinations | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api<Destinations>(`${GUARDRAILS_BASE}/destinations`));
    } catch (err) {
      setError(formatApiError(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the tab's first load
    void load();
  }, [load]);

  async function setTrust(id: number, name: string, trust: TrustLevel) {
    try {
      await api(`${GUARDRAILS_BASE}/destinations/${id}`, { method: "PUT", body: JSON.stringify({ trust_level: trust }) });
      setNotice(`${name} is now ${TRUST.find((t) => t.key === trust)?.label.toLowerCase()}.`);
      setError("");
      await load();
      await onChanged();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div className="guardrails-destinations">
      <p className="muted-text">
        Internal: run by your organisation. Trusted external: an outside service under contract. Public: anything else.
        A new connection starts as Public, the strictest.
      </p>
      {error ? <p className="alert alert-error">{error}</p> : null}
      {notice ? <p className="alert alert-success">{notice}</p> : null}
      <div className="table-wrap">
        <table className="card data-table guardrails-table">
          <thead>
            <tr>
              <th>Destination</th>
              <th className="col-sm">Kind</th>
              <th className="col-md">Trust level</th>
            </tr>
          </thead>
          <tbody>
            {data === null ? (
              <tr>
                <td colSpan={3} className="muted-text">
                  Loading…
                </td>
              </tr>
            ) : (
              <>
                {data.connections.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.name}
                      {c.is_active ? null : <span className="muted-text"> · disabled</span>}
                    </td>
                    <td>{c.kind === "web_search" ? "Web search" : "Models"}</td>
                    <td>
                      <select
                        aria-label={`Trust level of ${c.name}`}
                        value={c.trust_level}
                        disabled={readOnly}
                        onChange={(e) => void setTrust(c.id, c.name, e.target.value as TrustLevel)}
                      >
                        {TRUST.map((t) => (
                          <option key={t.key} value={t.key}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
                {data.implicit.map((d) => (
                  <tr key={d.key}>
                    <td>{d.label}</td>
                    <td>{d.kind === "web_search" ? "Web search" : "Web fetch"}</td>
                    <td className="muted-text">Public (always)</td>
                  </tr>
                ))}
              </>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
