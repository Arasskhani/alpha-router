/**
 * What the administrator's Guardrails did to a turn, said to the person under
 * the answer: values masked before sending, or the model the turn was routed
 * to. The server sends the notices on the stream
 * (`alpha_router.guardrail.notices`) and keeps them with the saved answer
 * (`guardrailNotices`), so a reloaded chat shows them too. A blocked turn is
 * not here: it is refused before anything is sent, with its own message.
 */

const MAX_NOTICES = 10;
const MAX_LENGTH = 500;

export function readGuardrailNotices(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const notices: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") continue;
    const text = item.trim().slice(0, MAX_LENGTH);
    if (!text || notices.includes(text)) continue;
    notices.push(text);
    if (notices.length >= MAX_NOTICES) break;
  }
  return notices.length ? notices : undefined;
}
