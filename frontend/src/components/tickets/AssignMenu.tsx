import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { TicketAvatar } from "./TicketBadges";
import type { Assignee } from "../../lib/tickets";

/** Close a popover on a click outside `ref` or on Escape. */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close]);
}

/**
 * Give focus back to the button that opened a popover once it closes, when the
 * focus went down with it (a pick, Escape). A click on something else keeps
 * the focus there.
 */
export function useReturnFocus(open: boolean, triggerRef: RefObject<HTMLElement | null>) {
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    const active = document.activeElement;
    if (!active || active === document.body) triggerRef.current?.focus();
  }, [open, triggerRef]);
}

type Props = {
  assignees: Assignee[];
  /** The ticket's assignee now; null when unassigned or for a bulk assign. */
  currentId: number | null;
  /** Whether the person assigned by someone else gets an email (Settings). */
  emailsAssignee: boolean;
  /** Offer "Unassign" (a ticket that has an assignee). */
  canUnassign: boolean;
  /** Bulk: one email for every selected ticket. */
  bulk?: boolean;
  onPick: (assignee: Assignee | null) => void;
};

/**
 * Who a ticket can go to: "Assign to me" first (no email), then the support
 * team with their open counts (the person gets an email), then Unassign.
 * Plain buttons in a group (Tab moves through them), not a listbox: the person
 * assigned now is a disabled button that says so.
 */
export default function AssignMenu({ assignees, currentId, emailsAssignee, canUnassign, bulk, onPick }: Props) {
  const [query, setQuery] = useState("");
  const me = assignees.find((a) => a.is_me) ?? null;
  const others = useMemo(() => {
    const q = query.trim().toLowerCase();
    return assignees
      .filter((a) => !a.is_me)
      .filter((a) => !q || a.name.toLowerCase().includes(q) || a.username.toLowerCase().includes(q));
  }, [assignees, query]);
  const showMe = me && (!query.trim() || `${me.name} ${me.username}`.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div className="tickets-assign-pop" role="dialog" aria-label="Assign to">
      <input
        className="input-block"
        placeholder="Find a person"
        aria-label="Find a person"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- a picker the person just opened
        autoFocus
      />
      <div role="group" aria-label="People who can work tickets" className="tickets-assign-list">
        {showMe ? (
          <button
            type="button"
            className="tickets-assign-opt tickets-assign-opt--me"
            disabled={currentId === me.id}
            onClick={() => onPick(me)}
          >
            <TicketAvatar name={me.name} staff small />
            <span>
              <b>Assign to me</b>
              <small>
                <bdi>{me.name}</bdi> · {me.open_count} open
                {currentId === me.id ? " · assigned now" : ""}
              </small>
            </span>
            <span className="tickets-assign-tag">no email</span>
          </button>
        ) : null}
        {others.length ? <div className="tickets-assign-sep">Support team</div> : null}
        {others.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`tickets-assign-opt${currentId === a.id ? " is-current" : ""}`}
            disabled={currentId === a.id}
            onClick={() => onPick(a)}
          >
            <TicketAvatar name={a.name} staff={a.role_label === "Super Admin"} small />
            <span>
              <b dir="auto">{a.name}</b>
              <small>
                {a.role_label} · {a.open_count} open
                {currentId === a.id ? " · assigned now" : ""}
              </small>
            </span>
            {emailsAssignee && currentId !== a.id ? (
              <span className="tickets-assign-tag tickets-assign-tag--mail">✉ {bulk ? "gets one email" : "gets an email"}</span>
            ) : (
              <span />
            )}
          </button>
        ))}
        {!showMe && others.length === 0 ? <p className="tickets-assign-empty muted-text">Nobody matches.</p> : null}
        {canUnassign ? (
          <button type="button" className="tickets-assign-opt tickets-assign-opt--unassign" onClick={() => onPick(null)}>
            <span className="tickets-avatar tickets-avatar--xs tickets-avatar--none" aria-hidden>
              –
            </span>
            <span>
              <b>Unassign</b>
              <small>Nobody is emailed</small>
            </span>
            <span />
          </button>
        ) : null}
      </div>
      <p className="tickets-hint">
        Only people who can work tickets are listed: the Support role and Super Admins. Read-only admins are not.
      </p>
    </div>
  );
}
