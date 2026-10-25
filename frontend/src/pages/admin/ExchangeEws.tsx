import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import Tabs, { TabPanel } from "../../components/Tabs";
import ExchangeAccessTab from "../../components/exchange/ExchangeAccessTab";
import { errorText } from "../../components/exchange/ExchangeControls";
import ExchangeOverviewTab from "../../components/exchange/ExchangeOverviewTab";
import ExchangePeopleTab from "../../components/exchange/ExchangePeopleTab";
import ExchangeSettingsTab from "../../components/exchange/ExchangeSettingsTab";
import { bootstrapSession } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { useCachedSession } from "../../hooks/useCachedSession";
import { exchangeAdminApi, type ExchangeSettingsResponse } from "../../lib/exchangeMail";
import { GUIDE_HREF } from "../../lib/exchangeAdmin";
import { userHasSuperAdminAccess } from "../../lib/rbac";

type TabId = "overview" | "settings" | "access" | "people";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "settings", label: "Settings" },
  { id: "access", label: "Access" },
  { id: "people", label: "People" },
];

function readTab(value: string | null): TabId {
  return value === "settings" || value === "access" || value === "people" ? value : "overview";
}

/**
 * Integrations › Exchange EWS (/admin/exchange-ews): the Overview, the
 * Settings with Test connection, who may connect (Access) and the people
 * connected. The tab is kept in the address (`?tab=`), so the Overview and
 * the Admin Guide can link to one. Read-only administrators see everything
 * with every control disabled and no button that writes.
 */
export default function ExchangeEws() {
  const readOnly = useReadOnly();
  const session = useCachedSession();
  // Where Exchange passwords are sent is a Super Admin's decision (the server answers 403 super_admin_only).
  const superAdmin = userHasSuperAdminAccess(
    Array.isArray(session?.roles) ? (session.roles as string[]) : undefined,
    session?.role,
  );
  const [params, setParams] = useSearchParams();
  const tab = readTab(params.get("tab"));
  const [settings, setSettings] = useState<ExchangeSettingsResponse | null>(null);
  const [settingsError, setSettingsError] = useState("");
  const [testPassed, setTestPassed] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await exchangeAdminApi.settings());
      setSettingsError("");
    } catch (err) {
      setSettingsError(errorText(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the page's first load
    void loadSettings();
  }, [loadSettings]);

  function openTab(next: TabId) {
    // Each tab starts clean: the People filters and the test focus belong to the visit that set them.
    setParams(next === "overview" ? {} : { tab: next });
  }

  const off = settings ? !settings.settings.enabled : false;
  return (
    <AdminPage title="Exchange EWS">
      <p className="muted-text ews-admin-intro">
        People who sign in with Active Directory connect their own Exchange mailbox (Exchange Server 2019 or SE) and
        use it in the Chat: search, read, summarise, draft and find meeting times. What the Exchange administrator sets
        up first is in <Link to={GUIDE_HREF}>Admin Guide › Exchange EWS</Link>.
      </p>
      {off ? (
        <div className="alert alert-warning ews-admin-off" role="status">
          <strong>Exchange EWS is off.</strong> Nobody sees Connections or can connect a mailbox; existing connections
          are kept and not used.
          {tab !== "settings" ? (
            <>
              {" "}
              <Link to="?tab=settings">{readOnly ? "See Settings" : "Turn it on in Settings"}</Link>
            </>
          ) : null}
        </div>
      ) : null}
      <Tabs items={TABS} value={tab} onChange={openTab} ariaLabel="Exchange EWS" idBase="ews-admin" />
      <TabPanel id={tab} idBase="ews-admin" className="ews-admin-panel">
        {tab === "overview" ? <ExchangeOverviewTab settings={settings} testPassed={testPassed} /> : null}
        {tab === "settings" ? (
          <ExchangeSettingsTab
            key={settings ? "ready" : "loading"}
            data={settings}
            loadError={settingsError}
            onRetry={() => {
              setSettingsError("");
              void loadSettings();
            }}
            canEdit={!readOnly}
            canEditEndpoint={!readOnly && superAdmin}
            focusTest={params.get("focus") === "test"}
            onTestPassed={() => setTestPassed(true)}
            onSaved={(next) => {
              const switched = settings?.settings.enabled !== next.settings.enabled;
              setSettings(next);
              // On or off changes this account's own menus too (features.connections).
              if (switched) void bootstrapSession(true).catch(() => undefined);
            }}
          />
        ) : null}
        {tab === "access" ? <ExchangeAccessTab canEdit={!readOnly} /> : null}
        {tab === "people" ? <ExchangePeopleTab canEdit={!readOnly} /> : null}
      </TabPanel>
    </AdminPage>
  );
}
