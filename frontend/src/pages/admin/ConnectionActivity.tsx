import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api";
import ActivityView from "../../components/activity/ActivityView";
import type { ActivityPayload } from "../../components/activity/types";
import ConnectionChangelog from "../../components/connections/ConnectionChangelog";

type ConnectionMeta = {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  is_active: boolean;
};

export default function ConnectionActivity() {
  const { connId } = useParams();
  const id = Number(connId);
  const [meta, setMeta] = useState<ConnectionMeta | null>(null);
  const [toggleBusy, setToggleBusy] = useState(false);
  const [toggleMsg, setToggleMsg] = useState("");

  const onActivityLoaded = useCallback((data: ActivityPayload) => {
    const c = data.connection;
    if (!c) return;
    setMeta({
      id: c.id,
      name: c.name,
      provider_type: c.provider_type,
      base_url: c.base_url ?? null,
      is_active: c.is_active,
    });
  }, []);

  async function toggleActive() {
    if (!meta) return;
    setToggleBusy(true);
    setToggleMsg("");
    try {
      const res = await api<{ is_active: boolean }>(
        `/api/admin/connections/${meta.id}/toggle?enabled=${!meta.is_active}`,
        { method: "PATCH" },
      );
      setMeta((m) => (m ? { ...m, is_active: res.is_active } : m));
      setToggleMsg(res.is_active ? "Connection enabled." : "Connection disabled.");
    } catch (ex) {
      setToggleMsg(String(ex));
    } finally {
      setToggleBusy(false);
    }
  }

  const toolbarExtra =
    meta ? (
      <div className="connection-activity-actions">
        <button
          type="button"
          className={`btn btn-ghost btn-sm${meta.is_active ? "" : " connection-activity-actions__enable"}`}
          disabled={toggleBusy}
          onClick={() => void toggleActive()}
        >
          {toggleBusy ? "…" : meta.is_active ? "Disable connection" : "Enable connection"}
        </button>
        {toggleMsg ? <span className="muted-text connection-activity-actions__msg">{toggleMsg}</span> : null}
      </div>
    ) : null;

  return (
    <ActivityView
      scope="connection"
      connectionId={id}
      backLink={{ to: "/admin/connections", label: "Connections" }}
      toolbarExtra={toolbarExtra}
      onDataLoaded={onActivityLoaded}
      footer={Number.isFinite(id) ? <ConnectionChangelog connectionId={id} /> : null}
    />
  );
}
