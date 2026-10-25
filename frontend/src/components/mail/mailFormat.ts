/**
 * Exchange mailbox (the person's side): what a person reads when the server
 * refuses, and the small labels the Connections page and the mail toasts share.
 */
import { MailApiError, type ActionItem } from "../../lib/exchangeMail";

/** Where the refusal came from: a wrong password reads differently when typing it than when it was saved. */
export type MailErrorContext = "connect" | "mailbox" | "action";

/** The codes after which the page's picture of the connection is out of date: read it again. */
export const STALE_CODES = new Set([
  "not_eligible",
  "not_connected",
  "needs_password",
  "exchange_auth",
  "connection_error",
  "connect_in_progress",
]);

/** What a person reads when Exchange refuses EWS for their login (HTTP 403): only an administrator can fix it. */
export const EXCHANGE_BLOCKED_TEXT =
  "Exchange refused EWS for your login: EWS may be turned off for your mailbox, or Alpharouter is not on the EWS allow list. Tell your administrator.";

export function mailErrorCode(err: unknown): string | null {
  return err instanceof MailApiError ? err.code : null;
}

/** A short sentence for a refusal, by the server's code. */
export function mailErrorText(err: unknown, context: MailErrorContext = "action", maxMailboxes?: number): string {
  if (!(err instanceof MailApiError)) {
    return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
  }
  switch (err.code) {
    case "exchange_auth":
      return context === "connect"
        ? "Exchange did not accept this password. Check it and try again. Several wrong tries in a row can lock your account."
        : "Exchange no longer accepts your saved password. Enter your current password under Update password.";
    case "mailbox_mismatch":
      return "This password opens a different mailbox than yours. Use your own password.";
    case "too_many_attempts":
      return "Too many tries. Wait 15 minutes, then try again.";
    case "exchange_unreachable":
      return "Alpharouter cannot reach the Exchange server. Try again later, or tell your administrator.";
    case "exchange_tls":
      return "The Exchange server's certificate is not trusted. Tell your administrator.";
    case "exchange_throttled":
      return "Exchange is busy right now. Wait a minute, then try again.";
    case "not_eligible":
      return err.serverMessage ? err.message : "Your account cannot connect a mailbox.";
    case "not_connected":
      return "Your mailbox is not connected.";
    case "needs_password":
      return "Your password is needed again. Enter it under Update password.";
    case "connection_error":
      return "The connection to your mailbox stopped: the saved password opened a mailbox other than yours. Enter your own password under Update password to reconnect.";
    case "exchange_blocked":
      return EXCHANGE_BLOCKED_TEXT;
    case "connect_in_progress":
      return "Your mailbox is being connected in another window. Wait a moment, then try again.";
    case "send_in_progress":
      return "This draft is already being sent from another window.";
    case "invalid_address":
      return "That is not a valid email address.";
    case "already_added":
      return "This mailbox is already in your list.";
    case "too_many_mailboxes":
      // The limit counts Full Access mailboxes; the person's own is not one of them.
      return maxMailboxes
        ? `You can have at most ${maxMailboxes} Full Access ${maxMailboxes === 1 ? "mailbox" : "mailboxes"}. Remove one first.`
        : "You have the most Full Access mailboxes allowed. Remove one first.";
    case "exchange_access_denied":
      return "You do not have access to this mailbox. Ask your Exchange administrator for Full Access.";
    case "exchange_not_found":
      return context === "mailbox" ? "No mailbox was found at this address." : "This email was not found in Exchange.";
    case "manual_mailboxes_off":
      return "Adding mailboxes yourself is turned off by your administrator.";
    case "own_mailbox":
      return "Your own mailbox cannot be turned off or removed.";
    default:
      break;
  }
  if (err.status === 429) return "Too many requests. Wait a little, then try again.";
  if (err.serverMessage && err.message) return err.message;
  return `Something went wrong (${err.status}). Try again.`;
}

/** "Sara Karimi", else the address, else "Unknown sender". */
export function senderLabel(item: Pick<ActionItem, "sender_name" | "sender_email">): string {
  return (item.sender_name ?? "").trim() || (item.sender_email ?? "").trim() || "Unknown sender";
}

export function subjectLabel(subject: string | null | undefined): string {
  return (subject ?? "").trim() || "(no subject)";
}
