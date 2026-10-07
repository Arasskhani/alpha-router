import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import ExtensionSettingsCard from "../../components/admin/ExtensionSettingsCard";
import { api, formatApiError } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";

/**
 * The browser extension, in one place.
 *
 * Who may use the extension and its agent stays on Chat Tools, with the other
 * tools, and on Feature Access (its Browser extension section); everything else about it lives here: what is happening right now, the
 * two things an administrator reaches for when it is not (stop the runs,
 * disconnect the browsers), and every setting that governs it.
 */

type Overview = {
  enabled: boolean;
  full_control: boolean;
  package_version: string | null;
  browsers: { connected: number; outdated: number; unknown_version: number };
  today: { agent_runs: number; actions_refused: number };
  stop_runs_before: string | null;
};

const OVERVIEW_PATH = "/api/admin/extension/overview";

function isOverview(value: unknown): value is Overview {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<Overview>;
  return typeof v.enabled === "boolean" && Boolean(v.browsers) && Boolean(v.today);
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="extension-overview__tile">
      <span className="extension-overview__value">{value}</span>
      <span className="extension-overview__label">{label}</span>
      {hint ? <span className="extension-overview__hint muted-text">{hint}</span> : null}
    </div>
  );
}

/** A moment as the page shows it, in the reader's own time zone. */
function shownTime(raw: string | null): string | null {
  if (!raw) return null;
  const when = new Date(raw);
  return Number.isNaN(when.getTime()) ? null : when.toLocaleString();
}

export default function BrowserExtension() {
  const readOnly = useReadOnly();
  const { confirm } = useConfirm();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const loaded = await api<Overview>(OVERVIEW_PATH);
      if (!isOverview(loaded)) throw new Error("The overview could not be read.");
      setOverview(loaded);
    } catch (err) {
      setError(formatApiError(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the effect's job is the fetch
    void load();
  }, [load]);

  async function act(path: string, what: string, done: (body: Record<string, unknown>) => string) {
    setBusy(path);
    setError("");
    setNotice("");
    try {
      const body = await api<Record<string, unknown>>(path, { method: "POST" });
      setNotice(done(body ?? {}));
      await load();
    } catch (err) {
      setError(`${what}: ${formatApiError(err)}`);
    } finally {
      setBusy("");
    }
  }

  async function stopRuns() {
    const ok = await confirm({
      title: "Stop every agent run?",
      message:
        "Each run under way ends at its next step, and the person is told their administrator stopped it. Runs started after this are unaffected.",
      confirmLabel: "Stop the runs",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (ok === true) await act("/api/admin/extension/stop-runs", "The runs could not be stopped", () => "Every run under way will stop at its next step.");
  }

  async function disconnectAll() {
    const ok = await confirm({
      title: "Disconnect every browser?",
      message:
        "Every connected browser is signed out of the extension. People connect again from the extension's side panel.",
      confirmLabel: "Disconnect all",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (ok === true) {
      await act("/api/admin/extension/disconnect-all", "The browsers could not be disconnected", (body) => {
        const count = typeof body.disconnected === "number" ? body.disconnected : 0;
        return count === 1 ? "One browser was disconnected." : `${count} browsers were disconnected.`;
      });
    }
  }

  const stopped = shownTime(overview?.stop_runs_before ?? null);

  return (
    <AdminPage title="Browser Extension">
      <p className="settings-section-desc">
        Alpharouter in Chrome and Edge: a side panel beside any page, and — where you allow it — an agent that works
        in the person&apos;s tabs. Who may use it is on{" "}
        <Link to="/admin/chat-tools">Chat Tools</Link> (Browser Extension, Browser Agent, Browser Control) and on{" "}
        <Link to="/admin/feature-access">Feature Access</Link> (Browser extension). Every change here is recorded in
        Admin Logs.
      </p>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      ) : null}

      <section className="settings-section" aria-labelledby="extension-overview-title">
        <h2 id="extension-overview-title">Right now</h2>
        {!overview ? (
          error ? null : <p className="muted-text">Loading…</p>
        ) : (
          <>
            <div className="extension-overview">
              <Tile label="Extension" value={overview.enabled ? "On" : "Off"} hint={overview.enabled ? undefined : "Nobody can use it"} />
              <Tile label="Full control" value={overview.full_control ? "On" : "Off"} />
              <Tile
                label="Connected browsers"
                value={String(overview.browsers.connected)}
                hint={
                  overview.browsers.outdated
                    ? `${overview.browsers.outdated} on an older package`
                    : overview.browsers.unknown_version
                      ? `${overview.browsers.unknown_version} have not said which package`
                      : undefined
                }
              />
              <Tile label="Agent runs today" value={String(overview.today.agent_runs)} />
              <Tile label="Actions refused today" value={String(overview.today.actions_refused)} hint="Blocked by the rules, or denied by the person" />
              <Tile label="Package" value={overview.package_version ?? "—"} hint={overview.package_version ? undefined : "Not available for download"} />
            </div>
            {stopped ? (
              <p className="settings-row__hint">
                Runs that began before <strong>{stopped}</strong> were stopped. Anything started since runs normally.
              </p>
            ) : null}
            {readOnly ? null : (
              <div className="dialog-actions">
                <button type="button" className="btn btn--danger" onClick={() => void stopRuns()} disabled={Boolean(busy)}>
                  Stop all agent runs now
                </button>
                <button type="button" className="btn btn--ghost" onClick={() => void disconnectAll()} disabled={Boolean(busy)}>
                  Disconnect all browsers
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <ExtensionSettingsCard />
    </AdminPage>
  );
}
