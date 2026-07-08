/** Distance from bottom (px) still treated as "pinned" for auto-scroll. */
export const CHAT_SCROLL_PIN_THRESHOLD = 96;

export function isNearScrollBottom(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">,
  threshold = CHAT_SCROLL_PIN_THRESHOLD,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

export function scrollContainerToBottom(el: HTMLElement, behavior: ScrollBehavior = "auto"): void {
  const top = el.scrollHeight;
  if (behavior === "auto") {
    el.scrollTop = top;
    return;
  }
  el.scrollTo({ top, behavior });
}
