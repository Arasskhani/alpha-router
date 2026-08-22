/** Distance from bottom (px) still treated as "pinned" for auto-scroll. */
export const CHAT_SCROLL_PIN_THRESHOLD = 96;

export function isNearScrollBottom(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">,
  threshold = CHAT_SCROLL_PIN_THRESHOLD,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

export function isChatScrollable(
  el: Pick<HTMLElement, "scrollHeight" | "clientHeight">,
  slack = 24,
): boolean {
  return el.scrollHeight > el.clientHeight + slack;
}

/** Jump-to-bottom control: only when the thread overflows and the user is not pinned. */
export function chatScrollJumpButtonVisible(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">,
): boolean {
  return isChatScrollable(el) && !isNearScrollBottom(el);
}

/**
 * Pin follows the viewport, not distance-from-top.
 * A long thread at the bottom has a large scrollTop and must stay pinned.
 */
export function scrollPinFromViewport(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">,
): boolean {
  return isNearScrollBottom(el);
}

export function scrollContainerToBottom(el: HTMLElement, behavior: ScrollBehavior = "auto"): void {
  const top = el.scrollHeight;
  if (behavior === "auto") {
    el.scrollTop = top;
    return;
  }
  el.scrollTo({ top, behavior });
}
