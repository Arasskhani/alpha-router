/**
 * What the administrator's Guardrails did to a turn, said to the person.
 *
 * Notices (values masked before sending, or the model the turn was routed
 * to) come on the turn's stream (`alpha_router.guardrail.notices`) and are
 * kept with the saved answer (`guardrailNotices`), so a reloaded chat shows
 * them too. A refused turn comes as a 422 (`guardrail_blocked`) or, when what
 * the platform added was refused, as `alpha_router.guardrail.blocked` on the
 * stream; the chat keeps it as a refusal in place of an answer
 * (`guardrailBlocked`), and the person's message held back
 * (`guardrailHeldBack`): it is never sent to a model again.
 */

export type GuardrailNotice = { action: "redact" | "route" | "notice"; message: string };

const MAX_NOTICES = 10;
const MAX_LENGTH = 500;

function clean(value: unknown): string {
  return typeof value === "string" ? value.trim().slice(0, MAX_LENGTH) : "";
}

export function readGuardrailNotices(value: unknown): GuardrailNotice[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const notices: GuardrailNotice[] = [];
  for (const item of value) {
    // Answers saved before notices said their action carry the text alone.
    const raw = typeof item === "string" ? { message: item } : item && typeof item === "object" ? (item as Record<string, unknown>) : null;
    const message = clean(raw?.message);
    if (!message || notices.some((n) => n.message === message)) continue;
    const action = raw?.action === "redact" || raw?.action === "route" ? raw.action : "notice";
    notices.push({ action, message });
    if (notices.length >= MAX_NOTICES) break;
  }
  return notices.length ? notices : undefined;
}

export type GuardrailRefusal = {
  message: string;
  /** What the chat keeps of the person's message: its found values replaced by hints. */
  userContent?: string;
  /** The server kept the turn: the client does not write it again. */
  persisted: boolean;
  /** The person's own message was refused (held back); else what the platform added was. */
  heldBack: boolean;
};

export class GuardrailRefusalError extends Error {
  readonly refusal: GuardrailRefusal;

  constructor(refusal: GuardrailRefusal) {
    super(refusal.message);
    this.name = "GuardrailRefusalError";
    this.refusal = refusal;
  }
}

export const GUARDRAIL_BLOCKED_CODE = "guardrail_blocked";
const FALLBACK_MESSAGE = "Your organisation does not allow this to be sent to AI models.";

/** A refusal from a 422's detail (`{code: "guardrail_blocked", message, user_content, persisted}`). */
export function refusalFromDetail(detail: unknown): GuardrailRefusal | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, unknown>;
  if (d.code !== GUARDRAIL_BLOCKED_CODE) return null;
  const userContent = typeof d.user_content === "string" ? d.user_content : undefined;
  return {
    message: clean(d.message) || FALLBACK_MESSAGE,
    ...(userContent !== undefined ? { userContent } : {}),
    persisted: d.persisted === true,
    heldBack: true,
  };
}

/** A refusal from the stream (`alpha_router.guardrail.blocked`): what the platform added was refused. */
export function refusalFromStream(value: unknown): GuardrailRefusal | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  return { message: clean(v.message) || FALLBACK_MESSAGE, persisted: v.persisted === true, heldBack: false };
}

/** A saved refusal (`guardrailBlocked: {message}`). */
export function readGuardrailBlocked(value: unknown): { message: string } | undefined {
  if (!value || typeof value !== "object") return undefined;
  const message = clean((value as Record<string, unknown>).message);
  return message ? { message } : undefined;
}
