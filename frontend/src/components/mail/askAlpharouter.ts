/**
 * "Ask Alpharouter" on an email that needs action: the server makes a short
 * reference for the email and the prompt about it; a new chat opens with that
 * prompt in its composer, not sent, for the person to read and send.
 */
import { requestChatPrefill } from "../../lib/chatPrefill";
import { mailApi } from "../../lib/exchangeMail";

/**
 * Where the chat opens: the personal chat of the panel the person is in (Mail
 * is not offered in project chats). An administrator asking from the admin
 * panel stays in it.
 */
function chatPathFor(currentPath: string): string {
  return currentPath === "/admin" || currentPath.startsWith("/admin/") ? "/admin/chat" : "/app/chat";
}

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
  const chat = chatPathFor(here);
  if (here !== chat) navigate(chat);
}
