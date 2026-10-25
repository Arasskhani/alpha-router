/**
 * "Ask Alpharouter" on an email that needs action: the server makes a short
 * reference for the email and the prompt about it; a new chat opens with that
 * prompt in its composer, not sent, for the person to read and send.
 */
import { requestChatPrefill } from "../../lib/chatPrefill";
import { mailApi } from "../../lib/exchangeMail";

/** Where the chat opens. Mail is not offered in project chats, so this is the personal chat. */
const PERSONAL_CHAT_PATH = "/app/chat";
const CHAT_PATHS = new Set([PERSONAL_CHAT_PATH, "/admin/chat"]);

/**
 * Ask for the prompt, then open the chat with it. Throws the server's refusal
 * (MailApiError) for the caller to show; nothing opens then.
 */
export async function askAlpharouter(
  id: number,
  navigate: (to: string) => void,
  currentPath: string,
): Promise<void> {
  const { prompt } = await mailApi.askAction(id);
  requestChatPrefill(prompt);
  // A chat page already open takes the prompt where it is.
  const here = currentPath.replace(/\/$/, "");
  if (!CHAT_PATHS.has(here)) navigate(PERSONAL_CHAT_PATH);
}
