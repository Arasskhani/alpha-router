/**
 * The side panel's conversation, minus the UI: which models, what a turn sends.
 *
 * Not "chat.ts": beside Chat.tsx that name differs only in case, and on a
 * disk that ignores case (Windows, macOS) "./chat" then resolves to the
 * component, since .tsx comes first in the resolver's extensions.
 */

import { modelSupportsTextChat } from "../../../src/lib/chatModels";
import { declaredSites, pageMessageContent, type MessageContent, type PageContext } from "../lib/pageContext";

export type ChatModel = {
  id: string;
  name: string;
  external_id?: string;
  kinds?: string[];
  is_system_default?: boolean;
  default_kinds?: string[];
  /** Takes an image as input: a screenshot may go to it. */
  supports_vision?: boolean;
};

export type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  /** Shown instead of (or after) the content; never sent back to the model. */
  error?: string;
  stopped?: boolean;
  /** Pages the user shared with this question. They go to the model with it on every later turn too. */
  pages?: PageContext[];
};

export function textModels(models: ChatModel[]): ChatModel[] {
  return models.filter((model) => modelSupportsTextChat(model));
}

/** The remembered choice while it is still offered; else the admin's chat default; else the first. */
export function pickModel(models: ChatModel[], remembered: string | null): ChatModel | null {
  return (
    models.find((m) => m.id === remembered) ??
    models.find((m) => m.default_kinds?.includes("chat")) ??
    models.find((m) => m.is_system_default) ??
    models[0] ??
    null
  );
}

/** The turns the model reads: failed and empty answers left out. */
function sentTurns(turns: Turn[]): Turn[] {
  return turns.filter((turn) => turn.role === "user" || (turn.content && !turn.error));
}

/**
 * The conversation as the model reads it. A shared page travels in its own
 * message just before the question it came with, so the question stays the
 * user's own words and the last message of its turn.
 */
export function apiMessages(turns: Turn[]): Array<{ role: string; content: MessageContent }> {
  return sentTurns(turns).flatMap((turn) => [
    ...(turn.pages ?? []).map((page) => ({ role: "user", content: pageMessageContent(page) })),
    { role: turn.role, content: turn.content },
  ]);
}

/** Whether the conversation carries a screenshot, which only a model that reads images can take. */
export function carriesScreenshots(pages: PageContext[]): boolean {
  return pages.some((page) => page.part === "screenshot");
}

/** Every page the conversation carries. */
export function pagesIn(turns: Turn[]): PageContext[] {
  return sentTurns(turns).flatMap((turn) => turn.pages ?? []);
}

export type CompletionRequest = {
  model: string;
  history: Turn[];
  user: Turn;
  assistantId: string;
  /** Null in Private: nothing is saved. */
  sessionId: string | null;
  sentAt: number;
};

export function completionBody(request: CompletionRequest): Record<string, unknown> {
  const turns = [...request.history, request.user];
  const messages = apiMessages(turns);
  const pages = pagesIn(turns);
  // The server checks each site and the model against the admin's rules, and records the share.
  const declaration = pages.length ? { extension_page_context: { sites: declaredSites(pages) } } : {};
  if (request.sessionId === null) {
    return { model: request.model, messages, stream: true, private_mode: true, ...declaration };
  }
  return {
    model: request.model,
    messages,
    stream: true,
    ...declaration,
    // The server saves the question and the answer as it streams, into a
    // chat it creates with this id when it does not exist yet.
    chat_session_id: request.sessionId,
    persist_chat: true,
    user_message: {
      role: "user",
      content: request.user.content,
      clientMessageId: request.user.id,
      sentAt: request.sentAt,
    },
    assistant_client_message_id: request.assistantId,
  };
}
