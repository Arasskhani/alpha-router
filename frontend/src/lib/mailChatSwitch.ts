/**
 * The Exchange mailbox in the chat: whether the envelope by the chat box
 * shows, whether this chat has mail on, and the flag a turn sends for it.
 *
 * Mail is not in the Tools menu. The server says the mailbox is connected and
 * working (`/api/auth/session` → `features.exchange_mail`); the person can then
 * turn mail off for one chat. That choice is kept with the chat's own stored
 * settings (`ChatToolsState.mailOff`, saved with the session like its tool
 * toggles, so it follows the chat to another device) rather than in this
 * browser alone.
 *
 * The server offers the mail tools only to a personal chat in the web app that
 * is not an Agent turn (a project chat is shared with its members, who would
 * see the person's mail), and it ignores the flag anywhere else. The client
 * does not ask there either, and hides the envelope, so it never promises mail
 * that a turn will not have.
 */

import { useEffect, useState } from "react";

import { bootstrapSession, getCachedSession, onSessionReady, type SessionInfo } from "../api";
import type { ChatToolsState } from "./chatTools";
import { MAIL_CHANGED_EVENT } from "./exchangeMail";

export const MAIL_ON_LABEL = "Exchange mailbox connected – mail is on for this chat";
export const MAIL_OFF_LABEL = "Mail is off for this chat";

/** True only when the server says so: an older server, or a missing block, means no mailbox. */
export function exchangeMailConnected(session: SessionInfo | null): boolean {
  const features = session?.features;
  if (!features || typeof features !== "object") return false;
  return (features as Record<string, unknown>).exchange_mail === true;
}

/**
 * The session's answer, kept current: read again when the server confirms a
 * session, and asked for again when the mailbox connection changes on this
 * page (connect, new password, disconnect: `MAIL_CHANGED_EVENT`).
 */
export function useExchangeMailConnected(): boolean {
  const [connected, setConnected] = useState(() => exchangeMailConnected(getCachedSession()));
  useEffect(() => {
    const stop = onSessionReady((session) => setConnected(exchangeMailConnected(session)));
    const reread = () => {
      void bootstrapSession(true).catch(() => undefined);
    };
    window.addEventListener(MAIL_CHANGED_EVENT, reread);
    return () => {
      stop();
      window.removeEventListener(MAIL_CHANGED_EVENT, reread);
    };
  }, []);
  return connected;
}

export type MailChatContext = {
  /** `features.exchange_mail` from the session. */
  connected: boolean;
  /** A project chat: shared with the project's members. */
  projectChat: boolean;
  /** An Agent is on for this chat. */
  agentMode: boolean;
};

/** Whether the envelope shows by the chat box. */
export function mailIndicatorShown(ctx: MailChatContext): boolean {
  return ctx.connected && !ctx.projectChat && !ctx.agentMode;
}

/** Mail is on for a chat unless the person turned it off there. */
export function mailOnForChat(tools: Pick<ChatToolsState, "mailOff">): boolean {
  return tools.mailOff !== true;
}

/** The chat's settings with mail switched the other way (absent again when on). */
export function toggleMailForChat(tools: ChatToolsState): ChatToolsState {
  const { mailOff, ...rest } = tools;
  return mailOff === true ? rest : { ...rest, mailOff: true };
}

/**
 * The chat's settings with mail on: "Ask Alpharouter" about an email puts its
 * prompt in an empty chat, and with mail off there the model could not open
 * the email it is asked about. Untouched when mail is already on.
 */
export function withMailOn(tools: ChatToolsState): ChatToolsState {
  return tools.mailOff === true ? toggleMailForChat(tools) : tools;
}

/**
 * A chat created for the first message keeps what the person chose before it
 * existed: fresh tools, with the mail switch carried over.
 */
export function withMailSwitchFrom(fresh: ChatToolsState, current: ChatToolsState): ChatToolsState {
  return current.mailOff === true ? { ...fresh, mailOff: true } : fresh;
}

/** A turn asks for mail only when the envelope shows and is on. */
export function mailToolRequested(ctx: MailChatContext, tools: Pick<ChatToolsState, "mailOff">): boolean {
  return mailIndicatorShown(ctx) && mailOnForChat(tools);
}

/** The request's tools with `exchange_mail: true` added when asked for; untouched otherwise. */
export function withMailTool<P extends { tools: object }>(payload: P, requested: boolean): P {
  return requested ? { ...payload, tools: { ...payload.tools, exchange_mail: true } } : payload;
}
