import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { StepIcon, errorText } from "./ExchangeControls";
import { exchangeAdminApi, type ExchangeOverview, type ExchangeSettingsResponse } from "../../lib/exchangeMail";
import { GUIDE_HREF, ago, fullTime, plural } from "../../lib/exchangeAdmin";

type Props = {
  settings: ExchangeSettingsResponse | null;
  /** A test passed on this page since it opened. */
  testPassed: boolean;
};

type Card = { key: string; title: string; value: string; note: string; to?: string; tooltip?: string };

function Stat({ card }: { card: Card }) {
  const value = <p className="overview-kpi-card__value">{card.value}</p>;
  return (
    <article className="overview-kpi-card card ews-admin-stat" data-testid={`ews-stat-${card.key}`} title={card.tooltip}>
      <p className="overview-kpi-card__title">{card.title}</p>
      {card.to ? (
        <Link to={card.to} className="ews-admin-stat__link" aria-label={`${card.title}: ${card.value}, open People`}>
          {value}
        </Link>
      ) : (
        value
      )}
      <p className="overview-kpi-card__note muted-text">{card.note}</p>
    </article>
  );
}

function Step({ done, title, detail, action }: { done: boolean | null; title: string; detail: ReactNode; action: ReactNode }) {
  return (
    <li className={`ews-admin-checklist__item${done ? " is-done" : done === false ? " is-todo" : ""}`}>
      <span className="ews-admin-checklist__mark" aria-hidden>
        {done ? <StepIcon state="ok" /> : <span className="ews-admin-checklist__dot" />}
      </span>
      <span className="ews-admin-checklist__text">
        <span className="ews-admin-checklist__title">
          {title}
          <span className="sr-only">{done ? ": done" : done === false ? ": to do" : ""}</span>
        </span>
        <span className="ews-admin-hint">{detail}</span>
      </span>
      <span className="ews-admin-checklist__action">{action}</span>
    </li>
  );
}

/**
 * Exchange EWS › Overview: who is connected and how it is going (counts only,
 * never an email), and what is left to set up.
 */
export default function ExchangeOverviewTab({ settings, testPassed }: Props) {
  const [overview, setOverview] = useState<ExchangeOverview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    exchangeAdminApi
      .overview()
      .then((next) => {
        if (!live) return;
        setOverview(next);
        setError("");
      })
      .catch((err: unknown) => {
        if (live) setError(errorText(err));
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  if (!overview) {
    return error ? (
      <div className="alert alert-error ews-admin-load-error" role="alert">
        <span>The overview could not be read: {error}</span>{" "}
        <button type="button" className="btn btn-ghost btn-sm btn-readonly-ok" onClick={() => setAttempt((n) => n + 1)}>
          Try again
        </button>
      </div>
    ) : (
      <p className="muted-text">Loading the overview…</p>
    );
  }

  const { counts } = overview;
  const cards: Card[] = [
    {
      key: "connected",
      title: "Connected",
      value: String(counts.connected),
      note: "mailboxes working",
      to: "?tab=people&status=connected",
    },
    {
      key: "needs_password",
      title: "Password needed",
      value: String(counts.needs_password),
      note: "the person enters it again",
      to: "?tab=people&status=needs_password",
    },
    {
      key: "error",
      title: "Error",
      value: String(counts.error),
      note: "Exchange failed several times",
      to: "?tab=people&status=error",
    },
    {
      key: "eligible",
      title: "Eligible AD accounts",
      value: String(overview.eligible_accounts),
      note: "active, Active Directory, with an email; Access list not applied",
    },
    { key: "actions", title: "Action items · 7 days", value: String(overview.action_items_7d), note: "emails flagged as needing action" },
    { key: "drafts", title: "Drafts · 7 days", value: String(overview.drafts_7d), note: "saved by the chat" },
    { key: "sent", title: "Sent · 7 days", value: String(overview.sent_7d), note: "after the person's review" },
    {
      key: "last_check",
      title: "Last check",
      value: ago(overview.last_check_at),
      note: "the newest needs-action check",
      tooltip: fullTime(overview.last_check_at),
    },
  ];

  const configured = overview.configured || Boolean(settings?.settings.ews_url);
  const tested = testPassed || counts.connected > 0;
  return (
    <div className="ews-admin-overview" data-ready="1">
      {/* People first, then the last 7 days: four to a row, two on a phone. */}
      <div className="overview-kpi-row ews-admin-stats" role="group" aria-label="Connections">
        {cards.slice(0, 4).map((card) => (
          <Stat key={card.key} card={card} />
        ))}
      </div>
      <div className="overview-kpi-row ews-admin-stats ews-admin-stats--last" role="group" aria-label="Last 7 days">
        {cards.slice(4).map((card) => (
          <Stat key={card.key} card={card} />
        ))}
      </div>

      <section className="ews-admin-card ews-admin-checklist" aria-labelledby="ews-admin-checklist-title">
        <h3 id="ews-admin-checklist-title">Setup</h3>
        <ol className="ews-admin-checklist__list">
          <Step
            done={configured}
            title="EWS address saved"
            detail={
              configured && settings?.ews_endpoint ? (
                <code dir="ltr">{settings.ews_endpoint}</code>
              ) : (
                "The address of Exchange Web Services, such as https://mail.corp.example/EWS/Exchange.asmx."
              )
            }
            action={<Link to="?tab=settings">{configured ? "Change" : "Open Settings"}</Link>}
          />
          <Step
            done={tested}
            title="Connection tested"
            detail={
              testPassed
                ? "A test passed on this page."
                : counts.connected > 0
                  ? `${plural(counts.connected, "person has", "people have")} connected, so the settings work.`
                  : "Run Test connection with your own AD account before turning it on."
            }
            action={<Link to="?tab=settings&focus=test">Test connection</Link>}
          />
          <Step
            done={overview.enabled}
            title="Turned on"
            detail={
              overview.enabled
                ? "People who sign in with Active Directory see Connections in their profile menu."
                : "Off: nobody sees Connections yet. Nothing is deleted while it is off."
            }
            action={<Link to="?tab=settings">{overview.enabled ? "Settings" : "Turn on in Settings"}</Link>}
          />
          <Step
            done={null}
            title="Who may connect"
            detail="Every Active Directory account until the list is restricted."
            action={<Link to="?tab=access">Access</Link>}
          />
        </ol>
        <p className="ews-admin-hint ews-admin-checklist__guide">
          What the Exchange administrator sets up first (EWS on, Windows authentication, Extended Protection, the
          certificate, Full Access): <Link to={GUIDE_HREF}>Admin Guide › Exchange EWS</Link>
        </p>
      </section>
    </div>
  );
}
