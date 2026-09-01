/** Distance from bottom (px) still treated as "pinned" for auto-scroll. */
export const CHAT_SCROLL_PIN_THRESHOLD = 96;
export function isNearScrollBottom(el, threshold = CHAT_SCROLL_PIN_THRESHOLD) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}
export function isChatScrollable(el, slack = 24) {
    return el.scrollHeight > el.clientHeight + slack;
}
/** Jump-to-bottom control: only when the thread overflows and the user is not pinned. */
export function chatScrollJumpButtonVisible(el) {
    return isChatScrollable(el) && !isNearScrollBottom(el);
}
/**
 * Pin follows the viewport, not distance-from-top.
 * A long thread at the bottom has a large scrollTop and must stay pinned.
 */
export function scrollPinFromViewport(el) {
    return isNearScrollBottom(el);
}
export function scrollContainerToBottom(el, behavior = "auto") {
    const top = el.scrollHeight;
    if (behavior === "auto") {
        el.scrollTop = top;
        return;
    }
    el.scrollTo({ top, behavior });
}
/**
 * Layout/image growth can fire `scroll` without a user gesture and must not
 * clear the pin; otherwise the thread stays mid-page after a tall media load.
 */
export function pinAfterScrollEvent(pinned, userInitiated, nearBottom) {
    if (userInitiated)
        return nearBottom;
    return pinned;
}
