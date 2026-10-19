import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useTableCards } from "../../hooks/useTableCards";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import { webSearchProviderLabel, type WebSearchProviderId } from "../../lib/webSearchProviders";
import RowActionsMenu from "../RowActionsMenu";
import WebSearchConnectionModal, { type WebSearchConnectionValues, type WebSearchTestResult } from "./WebSearchConnectionModal";

export type SearchConn = {
  id: number;
  name: string;
  kind: "web_search";
  provider_type: string;
  base_url: string | null;
  is_active: boolean;
  usage_usd: number;
  api_key_masked: string;
  priority: number;
  price_per_request_usd: number;
  config?: { cx?: string };
};

export type WebSearchOverview = {
  settings: { duckduckgo_fallback: boolean };
  plan: { label: string; provider: string; connection_id: number | null }[];
  available: boolean;
};

type Props = {
  rows: SearchConn[];
  /** The fallback switch and the order a search asks in, loaded with the connections. */
  overview: WebSearchOverview | null;
  setOverview: (overview: WebSearchOverview) => void;
  reload: () => Promise<void>;
  setMsg: (msg: string) => void;
  setErr: (err: string) => void;
  createOpen: boolean;
  onCreateClose: () => void;
};

function formatPrice(v: number) {
  if (!v) return "Free";
  return `$${v < 0.01 ? v.toFixed(4) : v.toFixed(3)}`;
}

function formatUsd(v: number) {
  if (v >= 1) return `$${v.toFixed(2)}`;
  if (v > 0) return `$${v.toFixed(4)}`;
  return "$0";
}

function body(values: WebSearchConnectionValues): Record<string, unknown> {
  return {
    name: values.name,
    provider_type: values.provider_type,
    base_url: values.base_url || null,
    config: values.engine_id ? { cx: values.engine_id } : {},
    priority: values.priority,
    price_per_request_usd: values.price_per_request_usd,
  };
}

/** The Web search tab of Connections: the search connections, the order a search asks them in, and the fallback. */
export default function WebSearchConnectionsPanel({
  rows,
  overview,
  setOverview,
  reload,
  setMsg,
  setErr,
  createOpen,
  onCreateClose,
}: Props) {
  const tableCardsRef = useTableCards<HTMLTableElement>();
  const { confirm } = useConfirm();
  const navigate = useNavigate();
  const [edit, setEdit] = useState<SearchConn | null>(null);

  async function create(values: WebSearchConnectionValues) {
    await api("/api/admin/connections", {
      method: "POST",
      body: JSON.stringify({ ...body(values), kind: "web_search", api_key: values.api_key }),
    });
    setMsg(`Web search connection "${values.name}" added.`);
    await reload();
  }

  async function update(values: WebSearchConnectionValues) {
    if (!edit) return;
    const patch: Record<string, unknown> = body(values);
    if (values.api_key) patch.api_key = values.api_key;
    await api(`/api/admin/connections/${edit.id}`, { method: "PATCH", body: JSON.stringify(patch) });
    setMsg("Web search connection updated.");
    await reload();
  }

  async function test(values: WebSearchConnectionValues, connectionId?: number): Promise<WebSearchTestResult> {
    return await api<WebSearchTestResult>("/api/admin/web-search/test", {
      method: "POST",
      body: JSON.stringify({
        ...(connectionId ? { connection_id: connectionId } : {}),
        provider_type: values.provider_type,
        api_key: values.api_key || null,
        base_url: values.base_url || null,
        config: values.engine_id ? { cx: values.engine_id } : {},
      }),
    });
  }

  async function testSaved(c: SearchConn) {
    try {
      const result = await api<WebSearchTestResult>("/api/admin/web-search/test", {
        method: "POST",
        body: JSON.stringify({ connection_id: c.id }),
      });
      if (result.ok) {
        setErr("");
        setMsg(`${c.name}: the search worked, ${result.count} results in ${result.elapsed_ms} ms.`);
      } else {
        setMsg("");
        setErr(`${c.name}: the search failed (${result.error.code}): ${result.error.message}`);
      }
    } catch (e) {
      setErr(String(e));
    }
  }

  async function toggle(c: SearchConn) {
    await api(`/api/admin/connections/${c.id}/toggle?enabled=${!c.is_active}`, { method: "PATCH" });
    setMsg(c.is_active ? `${c.name} is off: searches skip it.` : `${c.name} is on again.`);
    await reload();
  }

  async function remove(c: SearchConn) {
    const ok = await confirm({
      title: "Delete web search connection",
      message: `Delete "${c.name}"? Searches will no longer ask it. This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    await api(`/api/admin/connections/${c.id}`, { method: "DELETE" });
    setMsg(`Web search connection "${c.name}" deleted.`);
    await reload();
  }

  async function setFallback(on: boolean) {
    try {
      setOverview(
        await api<WebSearchOverview>("/api/admin/web-search", { method: "PUT", body: JSON.stringify({ duckduckgo_fallback: on }) }),
      );
      setMsg(on ? "DuckDuckGo is asked when the connections fail." : "DuckDuckGo is no longer asked.");
    } catch (e) {
      setErr(String(e));
    }
  }

  const sorted = [...rows].sort((a, b) => a.priority - b.priority || a.id - b.id);
  // One object per connection being edited: a new one on every render would reset the form as it is typed in.
  const editInitial = useMemo(
    () =>
      edit
        ? {
            name: edit.name,
            provider_type: edit.provider_type as WebSearchProviderId,
            base_url: edit.base_url ?? "",
            engine_id: edit.config?.cx ?? "",
            priority: edit.priority,
            price_per_request_usd: edit.price_per_request_usd,
            api_key_masked: edit.api_key_masked,
          }
        : undefined,
    [edit],
  );

  return (
    <>
      <div className="card web-search-fallback">
        <label>
          <input
            type="checkbox"
            checked={overview?.settings.duckduckgo_fallback ?? true}
            disabled={!overview}
            onChange={(e) => void setFallback(e.target.checked)}
          />{" "}
          Ask DuckDuckGo when the connections fail, or when there are none
        </label>
        <span className="muted-text">
          Free and needs no key, but it is read from DuckDuckGo&apos;s pages and is often rate limited. Turn it off to keep
          searches to the services you added.
        </span>
        {overview ? (
          <p className="muted-text web-search-order" data-testid="web-search-order">
            {overview.plan.length
              ? `A search asks, in order: ${overview.plan.map((step) => step.label).join(" → ")}.`
              : "Web Search is off in the chat: there is no search service to ask."}
          </p>
        ) : null}
      </div>

      <div className="table-wrap">
        <table ref={tableCardsRef} className="card data-table data-table--cards connections-table">
          <thead>
            <tr>
              <th>Name</th>
              <th className="col-md">Service</th>
              <th className="col-sm">Priority</th>
              <th className="col-sm">Per search</th>
              <th className="col-sm">Usage</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="muted-text">
                  No web search connections yet. Add one with + New web search connection.
                </td>
              </tr>
            )}
            {sorted.map((c) => (
              <tr key={c.id} className={c.is_active ? "" : "connections-row--disabled"}>
                <td>
                  <div className="connections-name-cell">
                    <strong>{c.name}</strong>
                    {!c.is_active ? <span className="connections-badge">Disabled</span> : null}
                  </div>
                </td>
                <td className="col-md">{webSearchProviderLabel(c.provider_type)}</td>
                <td className="col-sm">{c.priority}</td>
                <td className="col-sm">{formatPrice(c.price_per_request_usd)}</td>
                <td className="col-sm">
                  <strong>{formatUsd(c.usage_usd ?? 0)}</strong>
                </td>
                <td className="col-actions">
                  <RowActionsMenu
                    onError={setErr}
                    actions={[
                      { label: "Edit", onClick: () => setEdit(c) },
                      { label: "Test", onClick: () => testSaved(c) },
                      {
                        label: USAGE_AND_ACTIVITY_LABEL,
                        menuWrap: true,
                        onClick: () => navigate(`/admin/connections/${c.id}/activity`),
                      },
                      { label: c.is_active ? "Disable" : "Enable", onClick: () => toggle(c) },
                      { label: "Delete", onClick: () => remove(c), danger: true },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {createOpen ? (
      <WebSearchConnectionModal
        open
        title="Add web search connection"
        onClose={onCreateClose}
        onSubmit={create}
        onTest={(values) => test(values)}
      />
      ) : null}
      {edit ? (
      <WebSearchConnectionModal
        open
        title="Edit web search connection"
        initial={editInitial}
        onClose={() => setEdit(null)}
        onSubmit={update}
        onTest={(values) => test(values, edit?.id)}
      />
      ) : null}
    </>
  );
}
