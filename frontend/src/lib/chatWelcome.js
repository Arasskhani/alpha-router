export const COMPOSER_WELCOME_PROMPT = "How can I help you today?";
export const COMPOSER_DEFAULT_PLACEHOLDER = "Ask anything";
export function getTimeOfDay(now = new Date()) {
    const hour = now.getHours();
    if (hour >= 5 && hour < 12)
        return "morning";
    if (hour >= 12 && hour < 18)
        return "afternoon";
    return "evening";
}
export function isReturningChatUser(sessions) {
    return sessions.some((s) => (s.messageCount ?? s.messages.length) > 0);
}
export function getChatWelcomeHeading(opts) {
    const name = opts.name.trim() || "there";
    if (opts.isReturning) {
        return `Welcome back, ${name}!`;
    }
    const timeOfDay = getTimeOfDay(opts.now);
    const greeting = timeOfDay === "morning"
        ? "Good morning"
        : timeOfDay === "afternoon"
            ? "Good afternoon"
            : "Good evening";
    return `${greeting}, ${name}!`;
}
export function shouldShowWelcomeComposerPrompt(opts) {
    return (opts.messageCount === 0 &&
        !opts.input.trim() &&
        opts.pendingAttachmentCount === 0 &&
        opts.queuedPromptCount === 0);
}
