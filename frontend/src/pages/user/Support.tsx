import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import SupportConversation from "../../components/support/SupportConversation";
import SupportList from "../../components/support/SupportList";
import { SupportOff } from "../../components/support/SupportBits";
import { isTicketsDisabled, supportErrorText } from "../../components/support/supportFormat";
import { SUPPORT_BASE, ticketsRequest, type SupportStatus } from "../../lib/tickets";

/**
 * Support: the person's tickets (list at /app/support, a conversation at
 * /app/support/:ticketId). /status comes first: it says whether Support is on,
 * and carries the categories, the image limits and the reporter shown on a
 * new ticket.
 */
export default function Support() {
  const { ticketId } = useParams();
  const [status, setStatus] = useState<SupportStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [disabled, setDisabled] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    ticketsRequest<SupportStatus>(`${SUPPORT_BASE}/status`)
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        setStatusError("");
        setDisabled(s.enabled === false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isTicketsDisabled(err)) setDisabled(true);
        else setStatusError(supportErrorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const onDisabled = useCallback(() => setDisabled(true), []);
  const reloadStatus = useCallback(() => setTick((n) => n + 1), []);

  if (disabled) {
    return (
      <AdminPage title="Support">
        <SupportOff />
      </AdminPage>
    );
  }

  if (!status) {
    return (
      <AdminPage title="Support">
        {statusError ? (
          <div className="alert alert-error support-alert" role="alert">
            <span>{statusError}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={reloadStatus}>
              Try again
            </button>
          </div>
        ) : (
          <p className="muted-text">Loading…</p>
        )}
      </AdminPage>
    );
  }

  if (ticketId !== undefined) {
    if (!/^\d+$/.test(ticketId)) {
      return (
        <AdminPage
          title="Support"
          actions={
            <Link to="/app/support" className="btn btn-ghost btn-readonly-ok support-back">
              ← My tickets
            </Link>
          }
        >
          <p className="support-empty" role="alert">
            This ticket was not found.
          </p>
        </AdminPage>
      );
    }
    return <SupportConversation key={ticketId} ticketId={Number(ticketId)} status={status} onDisabled={onDisabled} />;
  }

  return <SupportList status={status} onDisabled={onDisabled} onStatusStale={reloadStatus} />;
}
