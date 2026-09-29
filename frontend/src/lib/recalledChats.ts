/**
 * The person's earlier chats an answer read from (recall).
 *
 * A turn may read the related parts of the person's other chats; the answer
 * names them under its label, each a link back to that chat.
 */

export type RecalledChat = { id: string; title: string };

const MAX_SHOWN = 10;

export function readRecalledChats(value: unknown): RecalledChat[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const chats: RecalledChat[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const raw = item as Record<string, unknown>;
    if (typeof raw.id !== "string" || !raw.id.trim()) continue;
    chats.push({ id: raw.id, title: typeof raw.title === "string" ? raw.title : "" });
    if (chats.length >= MAX_SHOWN) break;
  }
  return chats.length ? chats : undefined;
}

export function recalledChatsLabel(chats: RecalledChat[]): string {
  return `Read from ${chats.length} earlier chat${chats.length === 1 ? "" : "s"}`;
}
