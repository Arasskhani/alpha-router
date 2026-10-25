/**
 * Draft cards under an answer: the drafts the model saved in the person's
 * mailbox during the turn (`alpha_router.mail_drafts` on the stream, `mailDrafts`
 * on the stored message), and what became of each one here.
 *
 * A card's stored copy says only what was saved. Whether it was sent or
 * discarded is the server's (`GET /api/mail/drafts/{id}`), and reading that
 * reads the draft live from Exchange, so cards do not ask on their own every
 * time a chat opens. The Review & send dialog asks; what it learns about a
 * finished draft (sent, discarded, failed: none of these can change again) is
 * kept for this tab, so the card still says "Sent" after the chat is reopened
 * or the page reloaded.
 */

import { readMailDraftCards, type DraftStatus, type MailDraft, type MailDraftCard } from "./exchangeMail";

/**
 * The cards so far with a frame's cards added: a frame may carry only the
 * drafts its round saved, or all of them again, so cards are joined by id
 * (a later copy of the same draft replaces the earlier one in place).
 */
export function mergeMailDraftCards(
  previous: MailDraftCard[] | undefined,
  next: MailDraftCard[] | undefined,
): MailDraftCard[] | undefined {
  if (!next?.length) return previous;
  if (!previous?.length) return next;
  const merged = [...previous];
  for (const card of next) {
    const at = merged.findIndex((c) => c.id === card.id);
    if (at >= 0) merged[at] = card;
    else merged.push(card);
  }
  return merged;
}

/** The cards one stream frame carries (`alpha_router.mail_drafts`), added to those already read. */
export function readStreamMailDrafts(
  previous: MailDraftCard[] | undefined,
  alphaRouter: unknown,
): MailDraftCard[] | undefined {
  if (!alphaRouter || typeof alphaRouter !== "object") return previous;
  return mergeMailDraftCards(previous, readMailDraftCards((alphaRouter as Record<string, unknown>).mail_drafts));
}

/** What cannot change again. `sending` can: it ends sent, or failed, or (a stale claim) back in Drafts. */
export type FinishedDraftStatus = Exclude<DraftStatus, "draft" | "sending">;
export type DraftOutcome = { status: FinishedDraftStatus; error: string | null };

const OUTCOMES_KEY = "alpha_router_mail_draft_outcomes";
const MAX_OUTCOMES = 100;
const FINISHED: FinishedDraftStatus[] = ["sent", "discarded", "failed"];

type StoredOutcome = DraftOutcome & { id: number };

/** Oldest first. Anything malformed (another version, a hand edit) reads as nothing known. */
function readOutcomes(): StoredOutcome[] {
  try {
    const raw = JSON.parse(sessionStorage.getItem(OUTCOMES_KEY) || "[]") as unknown;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (o): o is StoredOutcome =>
        !!o && typeof o === "object" && typeof o.id === "number" && FINISHED.includes(o.status),
    );
  } catch {
    return [];
  }
}

/** What this tab last learned about a finished draft, or null (still a draft, or not asked yet). */
export function knownDraftOutcome(id: number): DraftOutcome | null {
  const outcome = readOutcomes().find((o) => o.id === id);
  if (!outcome) return null;
  return { status: outcome.status, error: typeof outcome.error === "string" ? outcome.error : null };
}

/** Keep a finished draft's status for this tab; a draft still in Drafts is not kept. */
export function rememberDraftOutcome(draft: Pick<MailDraft, "id" | "status" | "error">): void {
  if (!FINISHED.includes(draft.status as FinishedDraftStatus)) return;
  try {
    const outcomes = readOutcomes().filter((o) => o.id !== draft.id);
    outcomes.push({ id: draft.id, status: draft.status as FinishedDraftStatus, error: draft.error ?? null });
    sessionStorage.setItem(OUTCOMES_KEY, JSON.stringify(outcomes.slice(-MAX_OUTCOMES)));
  } catch {
    // Storage full or blocked: the card still shows the outcome while it is on the page.
  }
}

/** "Sara Karimi, ali@corp.example" – names where known, addresses otherwise. */
export function recipientNames(list: { name: string; email: string }[]): string {
  return list.map((a) => a.name.trim() || a.email).join(", ");
}
