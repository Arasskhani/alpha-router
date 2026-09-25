/**
 * The side panel's chat, minus the UI: which models, what a turn sends.
 */

import { modelSupportsTextChat } from "../../../src/lib/chatModels";

export type ChatModel = {
  id: string;
  name: string;
  external_id?: string;
  kinds?: string[];
  is_system_default?: boolean;
  default_kinds?: string[];
};

export type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  /** Shown instead of (or after) the content; never sent back to the model. */
  error?: string;
  stopped?: boolean;
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

/** The conversation as the model reads it: failed and empty answers left out. */
export function apiMessages(turns: Turn[]): Array<{ role: string; content: string }> {
  return turns
    .filter((turn) => turn.role === "user" || (turn.content && !turn.error))
    .map((turn) => ({ role: turn.role, content: turn.content }));
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
  const messages = apiMessages([...request.history, request.user]);
  if (request.sessionId === null) {
    return { model: request.model, messages, stream: true, private_mode: true };
  }
  return {
    model: request.model,
    messages,
    stream: true,
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
