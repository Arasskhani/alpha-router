import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import Tabs, { TabPanel } from "../../components/Tabs";
import TicketsOverviewTab from "../../components/tickets/TicketsOverviewTab";
import TicketsQueueTab from "../../components/tickets/TicketsQueueTab";
import TicketsSettingsTab from "../../components/tickets/TicketsSettingsTab";
import { bootstrapSession } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { TICKETS_BASE, ticketsRequest, type StaffMeta, type TicketSettings } from "../../lib/tickets";

type TabId = "overview" | "tickets" | "settings";

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

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
  // Kept apart: the queue works without the settings, the Settings tab says why it is empty.
  const [settingsError, setSettingsError] = useState("");

  const loadMeta = useCallback(async () => {
    let settingsFailure = "";
    try {
      const [nextMeta, nextSettings] = await Promise.all([
        ticketsRequest<StaffMeta>(`${TICKETS_BASE}/meta`),
        ticketsRequest<TicketSettings>(`${TICKETS_BASE}/settings`).catch((err: unknown) => {
          settingsFailure = errorText(err);
          return null;
        }),
      ]);
      setMeta(nextMeta);
      if (nextSettings) setSettings(nextSettings);
      setSettingsError(settingsFailure);
      setError("");
    } catch (err) {
      setError(errorText(err));
      setSettingsError(settingsFailure);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the page's first load
    void loadMeta();
  }, [loadMeta]);

  const canWrite = !readOnly && Boolean(meta?.me.can_write);
  const isSuperAdmin = !readOnly && Boolean(meta?.me.is_super_admin);
  // The saved settings when read, else what /meta said; unknown counts as on (no warning on a guess).
  const supportOff = (settings?.enabled ?? meta?.settings.enabled) === false;
  const autoCloseDays = settings?.auto_close_days ?? meta?.settings.auto_close_days ?? 7;

  return (
    <AdminPage title="Tickets">
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {supportOff ? (
        <div className="alert alert-warning tickets-off-banner" role="status">
          <strong>Support is off.</strong> People cannot see their tickets or answer replies, and no ticket email
          reaches them. Tickets waiting for an answer do not close on their own; when Support is turned on again,
          each of them gets its full {autoCloseDays} days.
          {tab !== "settings" ? (
            <>
              {" "}
              <Link to={TAB_PATHS.settings}>{isSuperAdmin ? "Turn it on in Settings" : "See Settings"}</Link>
            </>
          ) : null}
        </div>
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
          <TicketsQueueTab
            meta={meta}
            settings={settings}
            canWrite={canWrite}
            isSuperAdmin={isSuperAdmin}
          />
        ) : null}
        {tab === "settings" ? (
          <TicketsSettingsTab
            key={settings ? "ready" : "loading"}
            settings={settings}
            meta={meta}
            canEdit={isSuperAdmin}
            loadError={settingsError}
            onRetry={() => {
              setSettingsError("");
              void loadMeta();
            }}
            onSaved={(next) => {
              setSettings(next);
              void loadMeta();
              // Support on or off changes this account's own menus too (features.support).
              void bootstrapSession(true).catch(() => undefined);
            }}
          />
        ) : null}
      </TabPanel>
    </AdminPage>
  );
}
