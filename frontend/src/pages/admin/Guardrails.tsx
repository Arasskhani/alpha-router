import { useCallback, useEffect, useState } from "react";

import AdminPage from "../../components/AdminPage";
import Tabs, { TabPanel } from "../../components/Tabs";
import DestinationsTab from "../../components/guardrails/DestinationsTab";
import EventsTab from "../../components/guardrails/EventsTab";
import OverviewTab from "../../components/guardrails/OverviewTab";
import PatternsTab from "../../components/guardrails/PatternsTab";
import RulesTab from "../../components/guardrails/RulesTab";
import SettingsTab from "../../components/guardrails/SettingsTab";
import { api, formatApiError } from "../../api";
import { GUARDRAILS_BASE, type GuardrailsMeta, type Overview } from "../../lib/guardrails";

type TabId = "overview" | "rules" | "patterns" | "destinations" | "events" | "settings";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "rules", label: "Rules" },
  { id: "patterns", label: "Patterns" },
  { id: "destinations", label: "Destinations" },
  { id: "events", label: "Events" },
  { id: "settings", label: "Settings" },
];

/**
 * Admin › Guardrails: what may leave the organisation, to where, and for whom.
 * Every rule is the administrator's; nothing applies until one is turned on.
 */
export default function Guardrails() {
  const [tab, setTab] = useState<TabId>("rules");
  const [meta, setMeta] = useState<GuardrailsMeta | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [nextMeta, nextOverview] = await Promise.all([
        api<GuardrailsMeta>(`${GUARDRAILS_BASE}/meta`),
        api<Overview>(`${GUARDRAILS_BASE}/overview`),
      ]);
      setMeta(nextMeta);
      setOverview(nextOverview);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the page's first load
    void refresh();
  }, [refresh]);

  const rules = overview?.rules;
  return (
    <AdminPage title="Guardrails">
      <div className="guardrails-head">
        <p className="muted-text guardrails-intro">
          What may leave the organisation, to where, and for whom. Every rule is set here; nothing applies until you
          turn it on.
        </p>
        {rules ? (
          <div className="guardrails-status" aria-label="Rules in force">
            <span className="guardrails-pill">
              <span className="guardrails-dot guardrails-dot--enforce" aria-hidden />
              Enforcing {rules.enforce} {rules.enforce === 1 ? "rule" : "rules"}
            </span>
            <span className="guardrails-pill">
              <span className="guardrails-dot guardrails-dot--monitor" aria-hidden />
              Monitoring {rules.monitor}
            </span>
            {overview && overview.totals_7d.engine_error > 0 ? (
              <span className="guardrails-pill guardrails-pill--bad">
                <span className="guardrails-dot guardrails-dot--bad" aria-hidden />
                {overview.totals_7d.engine_error} engine {overview.totals_7d.engine_error === 1 ? "error" : "errors"} (7 days)
              </span>
            ) : (
              <span className="guardrails-pill">
                <span className="guardrails-dot guardrails-dot--enforce" aria-hidden />
                Engine healthy
              </span>
            )}
          </div>
        ) : null}
      </div>
      {error ? <p className="alert alert-error">{error}</p> : null}
      <Tabs items={TABS} value={tab} onChange={setTab} ariaLabel="Guardrails" idBase="guardrails" />
      <TabPanel id={tab} idBase="guardrails" className="guardrails-panel">
        {tab === "overview" ? <OverviewTab overview={overview} /> : null}
        {tab === "rules" ? <RulesTab meta={meta} overview={overview} onChanged={refresh} /> : null}
        {tab === "patterns" ? <PatternsTab meta={meta} onChanged={refresh} /> : null}
        {tab === "destinations" ? <DestinationsTab onChanged={refresh} /> : null}
        {tab === "events" ? <EventsTab meta={meta} /> : null}
        {tab === "settings" ? <SettingsTab /> : null}
      </TabPanel>
    </AdminPage>
  );
}
