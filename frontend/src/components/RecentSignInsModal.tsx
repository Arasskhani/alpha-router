import { useEffect, useState } from "react";

import { api, formatApiError } from "../api";
import { formatLocalDateTime } from "../lib/dateTime";
import {
  IDP_SIGN_OUT_NOTE,
  eventLabel,
  methodLabel,
  outcomeBadgeClass,
  reasonLabel,
  signOutIsRecordedByIdp,
} from "../lib/signInActivity";
import Modal from "./Modal";

type OwnSignIn = {
  occurred_at: string | null;
  event_type: string;
  outcome: string;
  reason_code: string | null;
  auth_method: string | null;
  ip: string | null;
  user_agent: string | null;
  current_session: boolean;
};

type Response = {
  auth_provider: string;
  limit: number;
  items: OwnSignIn[];
};

/**
 * What a person can say about a device from its user agent, in a few words.
 * Nothing here is authoritative — the string is whatever the client sent —
 * so it is a hint beside the address, not a fact of its own.
 */
export function deviceHint(userAgent: string | null): string {
  if (!userAgent) return "";
  const ua = userAgent;
  const os = /Windows/i.test(ua)
    ? "Windows"
    : /iPhone|iPad/i.test(ua)
      ? "iOS"
      : /Android/i.test(ua)
        ? "Android"
        : /Mac OS X|Macintosh/i.test(ua)
          ? "macOS"
          : /Linux/i.test(ua)
            ? "Linux"
            : "";
  const browser = /Edg\//i.test(ua)
    ? "Edge"
    : /OPR\/|Opera/i.test(ua)
      ? "Opera"
      : /Firefox\//i.test(ua)
        ? "Firefox"
        : /Chrome\//i.test(ua) && !/Chromium/i.test(ua)
          ? "Chrome"
          : /Safari\//i.test(ua)
            ? "Safari"
            : "";
  return [browser, os].filter(Boolean).join(" · ");
}

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * The account's own recent sign-ins, in a dialog over Settings.
 *
 * The list is the one way an ordinary user sees an attack on their account:
 * a run of failed attempts from an address they do not recognise. So the
 * failures are shown as plainly as the successes, and the row for the
 * session they are reading this in is marked so the rest can be judged
 * against it.
 */
export default function RecentSignInsModal({ open, onClose }: Props) {
  const [data, setData] = useState<Response | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    // Every open fetches afresh: the list is a security signal and a stale
    // one from an earlier open would be worse than a brief "Loading…".
    api<Response>("/api/user/settings/sign-ins")
      .then((r) => {
        if (!cancelled) {
          setData(r);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const loading = open && !data && !error;
  const federated = signOutIsRecordedByIdp(data?.auth_provider ?? null);
  const failures = data?.items.filter((i) => i.outcome === "failure").length ?? 0;

  return (
    <Modal open={open} title="Recent sign-ins" onClose={onClose} panelClassName="modal-panel--md modal-panel--fit">
      <div className="recent-sign-ins">
        <p className="muted-text recent-sign-ins__intro">
          The last {data?.limit ?? 20} sign-ins, failed attempts and forced sign-outs for your account, with the address
          each came from. If you see attempts you did not make, change your password and tell your administrator.
          {federated ? <> {IDP_SIGN_OUT_NOTE}</> : null}
        </p>
        {error ? (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        ) : null}
        {loading && !data ? <p className="muted-text">Loading…</p> : null}
        {data && data.items.length === 0 ? <p className="muted-text">No sign-ins have been recorded yet.</p> : null}
        {data && data.items.length > 0 ? (
          <>
            {failures > 0 ? (
              <p className="alert alert-warning recent-sign-ins__failures">
                {failures === 1 ? "1 failed attempt" : `${failures} failed attempts`} in this list.
              </p>
            ) : null}
            <ul className="recent-sign-ins__list">
              {data.items.map((item, index) => (
                <li
                  key={`${item.occurred_at}-${index}`}
                  className={`recent-sign-ins__item${item.current_session ? " is-current" : ""}`}
                >
                  <div className="recent-sign-ins__head">
                    <span className={outcomeBadgeClass(item)}>{eventLabel(item.event_type)}</span>
                    <span className="recent-sign-ins__time">{formatLocalDateTime(item.occurred_at)}</span>
                    {item.current_session ? <span className="recent-sign-ins__current">This session</span> : null}
                  </div>
                  <div className="recent-sign-ins__facts">
                    <span>{item.ip || "Address not recorded"}</span>
                    {deviceHint(item.user_agent) ? <span>{deviceHint(item.user_agent)}</span> : null}
                    <span>{methodLabel(item.auth_method)}</span>
                    {item.reason_code ? <span>{reasonLabel(item.reason_code)}</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
