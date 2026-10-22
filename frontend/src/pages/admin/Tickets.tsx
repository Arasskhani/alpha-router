import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import Tabs, { TabPanel } from "../../components/Tabs";
import TicketsOverviewTab from "../../components/tickets/TicketsOverviewTab";
import TicketsSettingsTab from "../../components/tickets/TicketsSettingsTab";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { TICKETS_BASE, ticketsRequest, type StaffMeta, type TicketSettings } from "../../lib/tickets";

type TabId = "overview" | "tickets" | "settings";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tickets", label: "Tickets" },
  { id: "settings", label: "Settings" },
];

const TAB_PATHS: Record<TabId, string> = {
  overview: "/admin/tickets",
  tickets: "/admin/tickets/list",
  settings: "/admin/tickets/settings",
};

function tabFromPath(pathname: string): TabId {
  if (pathname.startsWith("/admin/tickets/list")) return "tickets";
  if (pathname.startsWith("/admin/tickets/settings")) return "settings";
  return "overview";
}

/**
 * Admin › Tickets: the Overview (opens first), the queue staff work, and
 * Settings. Support and Super Admin work tickets; Read Only Super Admin sees
 * everything and changes nothing; settings and every delete are Super Admin's.
 */
export default function Tickets() {
  const location = useLocation();
  const navigate = useNavigate();
  const readOnly = useReadOnly();
  const tab = tabFromPath(location.pathname);
  const [meta, setMeta] = useState<StaffMeta | null>(null);
  const [settings, setSettings] = useState<TicketSettings | null>(null);
  const [error, setError] = useState("");

  const loadMeta = useCallback(async () => {
    try {
      const [nextMeta, nextSettings] = await Promise.all([
        ticketsRequest<StaffMeta>(`${TICKETS_BASE}/meta`),
        ticketsRequest<TicketSettings>(`${TICKETS_BASE}/settings`).catch(() => null),
      ]);
      setMeta(nextMeta);
      if (nextSettings) setSettings(nextSettings);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the page's first load
    void loadMeta();
  }, [loadMeta]);

  const canWrite = !readOnly && Boolean(meta?.me.can_write);
  const isSuperAdmin = !readOnly && Boolean(meta?.me.is_super_admin);

  return (
    <AdminPage title="Tickets">
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      <Tabs
        items={TABS}
        value={tab}
        onChange={(id) => navigate(TAB_PATHS[id])}
        ariaLabel="Tickets"
        idBase="tickets"
      />
      <TabPanel id={tab} idBase="tickets" className="tickets-panel-tab">
        {tab === "overview" ? <TicketsOverviewTab /> : null}
        {tab === "tickets" ? (
          <p className="muted-text" data-can-write={canWrite}>
            Loading…
          </p>
        ) : null}
        {tab === "settings" ? (
          <TicketsSettingsTab
            key={settings ? "ready" : "loading"}
            settings={settings}
            meta={meta}
            canEdit={isSuperAdmin}
            onSaved={(next) => {
              setSettings(next);
              void loadMeta();
            }}
          />
        ) : null}
      </TabPanel>
    </AdminPage>
  );
}
