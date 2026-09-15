import type { ChatSession } from "./chatStorage";

export const COMPOSER_WELCOME_PROMPT = "How can I help you today?";
export const COMPOSER_DEFAULT_PLACEHOLDER = "Ask anything";

type TimeOfDay = "morning" | "afternoon" | "evening";

function getTimeOfDay(now = new Date()): TimeOfDay {
  const hour = now.getHours();
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 18) return "afternoon";
  return "evening";
}

export function isReturningChatUser(sessions: ChatSession[]): boolean {
  return sessions.some((s) => (s.messageCount ?? s.messages.length) > 0);
}

export function getChatWelcomeHeading(opts: {
  /** Prefer display name; username is an acceptable fallback. */
  name: string;
  isReturning: boolean;
  now?: Date;
}): string {
  const name = opts.name.trim() || "there";
  if (opts.isReturning) {
    return `Welcome back, ${name}!`;
  }
  const timeOfDay = getTimeOfDay(opts.now);
  const greeting =
    timeOfDay === "morning"
      ? "Good morning"
      : timeOfDay === "afternoon"
        ? "Good afternoon"
        : "Good evening";
  return `${greeting}, ${name}!`;
}

export function shouldShowWelcomeComposerPrompt(opts: {
  messageCount: number;
  input: string;
  pendingAttachmentCount: number;
  queuedPromptCount: number;
}): boolean {
  return (
    opts.messageCount === 0 &&
    !opts.input.trim() &&
    opts.pendingAttachmentCount === 0 &&
    opts.queuedPromptCount === 0
  );
}
