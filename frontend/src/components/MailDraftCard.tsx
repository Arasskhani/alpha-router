import { useCallback, useRef, useState } from "react";

import MailReviewDialog from "./MailReviewDialog";
import { IconMail } from "./icons/navIcons";
import {
  DRAFT_KIND_LABELS,
  isLiveDraft,
  safeOwaUrl,
  type MailDraft,
  type MailDraftCard as DraftCard,
  type MailDraftLive,
} from "../lib/exchangeMail";
import {
  knownDraftOutcome,
  recipientNames,
  rememberDraftOutcome,
  type DraftOutcome,
  type FinishedDraftStatus,
} from "../lib/mailDraftCards";

const OUTCOME_LABELS: Record<FinishedDraftStatus, string> = {
  sent: "Sent",
  discarded: "Discarded",
  failed: "Not sent",
};

/**
 * One draft the model saved in the person's mailbox, under its answer: what
 * kind, the subject, who it is to and how it begins. Nothing is sent from here:
 * **Review & send** reads the draft again from Exchange and sends it only when
 * the person says so. **Open in Outlook** appears once the draft's Outlook on
 * the web address is known (the dialog reads it).
 */
export default function MailDraftCard({ card }: { card: DraftCard }) {
  const [outcome, setOutcome] = useState<DraftOutcome | null>(() => knownDraftOutcome(card.id));
  const [owaUrl, setOwaUrl] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const cardRef = useRef<HTMLElement>(null);

  // Stable: the dialog reads the draft again whenever this changes.
  const onDraft = useCallback((draft: MailDraft | MailDraftLive) => {
    if (isLiveDraft(draft)) setOwaUrl(safeOwaUrl(draft.owa_url));
    rememberDraftOutcome(draft);
    setOutcome(draft.status === "draft" ? null : { status: draft.status, error: draft.error });
  }, []);

  const closeReview = () => {
    setReviewing(false);
    // A sent or discarded draft has no Review & send button to give focus back to: keep it on the card.
    window.setTimeout(() => {
      if (!document.activeElement || document.activeElement === document.body) cardRef.current?.focus();
    }, 0);
  };

  const kind = DRAFT_KIND_LABELS[card.kind] ?? DRAFT_KIND_LABELS.new;
  const subject = card.subject.trim() || "(no subject)";
  const to = recipientNames(card.to);
  // A sent or discarded draft is gone from Drafts; a failed one is still there to open.
  const showReview = !outcome;
  const showOutlook = !!owaUrl && (!outcome || outcome.status === "failed");
  return (
    <article
      ref={cardRef}
      tabIndex={-1}
      className={`mail-draft-card${outcome ? ` mail-draft-card--${outcome.status}` : ""}`}
      aria-label={`${kind}: ${subject}`}
    >
      <div className="mail-draft-card__head">
        <span className="mail-draft-card__icon" aria-hidden>
          <IconMail />
        </span>
        <span className="mail-draft-card__kind">{kind}</span>
        {outcome ? (
          <span className={`mail-draft-card__status mail-draft-card__status--${outcome.status}`}>
            {OUTCOME_LABELS[outcome.status]}
          </span>
        ) : null}
      </div>
      <p className="mail-draft-card__subject" dir="auto">
        {subject}
      </p>
      {to ? (
        <p className="mail-draft-card__to">
          <span className="mail-draft-card__label">To</span> <span dir="auto">{to}</span>
        </p>
      ) : null}
      {card.preview ? (
        <p className="mail-draft-card__preview" dir="auto">
          {card.preview}
        </p>
      ) : null}
      {outcome && outcome.status !== "sent" && outcome.error ? (
        <p className="mail-draft-card__error">{outcome.error}</p>
      ) : null}
      {showReview || showOutlook ? (
        <div className="mail-draft-card__actions">
          {showReview ? (
            <button type="button" className="btn btn-sm" onClick={() => setReviewing(true)}>
              Review &amp; send
            </button>
          ) : null}
          {showOutlook ? (
            <a className="btn btn-sm btn-ghost" href={owaUrl ?? undefined} target="_blank" rel="noopener noreferrer">
              Open in Outlook
            </a>
          ) : null}
        </div>
      ) : null}
      {reviewing ? <MailReviewDialog card={card} onDraft={onDraft} onClose={closeReview} /> : null}
    </article>
  );
}

/** The draft cards under an answer, in the order the model saved them. */
export function MailDraftCardList({ cards }: { cards: DraftCard[] }) {
  return (
    <div className="mail-draft-cards">
      {cards.map((card) => (
        <MailDraftCard key={card.id} card={card} />
      ))}
    </div>
  );
}
