/**
 * Grab-and-pull horizontal scrolling for a wide table.
 *
 * The API Logs table used to hide four columns below 1280px, which is how a
 * "Prompt Cache" column an operator relied on quietly disappeared on a laptop.
 * The table scrolls sideways instead now, and this makes that scroll reachable
 * with a mouse -- a trackpad has two-finger swipe, a mouse has nothing but the
 * scrollbar at the very bottom of a long page.
 *
 * Three things make drag-scrolling a table safe rather than annoying:
 *
 *   - It starts only after a deliberate horizontal movement. Below the
 *     threshold the browser's own text selection is untouched, so an operator
 *     can still select a model id or an error code out of a cell.
 *   - A drag that began on a control is ignored outright.
 *   - The click that ends a real drag is swallowed. Rows here open a detail
 *     panel; without this, pulling the table sideways would open whichever row
 *     the pointer happened to be over.
 */

/** Horizontal movement, in px, before a press becomes a drag. */
const DRAG_THRESHOLD_PX = 5;

const INTERACTIVE = "a, button, input, select, textarea, [role='button'], [contenteditable='true']";

export type DragScrollOptions = {
  /** Test seam; defaults to DRAG_THRESHOLD_PX. */
  threshold?: number;
};

/** Attach to a scroll container. Returns a cleanup function. */
export function attachDragScroll(el: HTMLElement, options: DragScrollOptions = {}): () => void {
  const threshold = options.threshold ?? DRAG_THRESHOLD_PX;

  let pointerId: number | null = null;
  let startX = 0;
  let startY = 0;
  let startScrollLeft = 0;
  let dragging = false;

  function reset() {
    if (pointerId != null) {
      try {
        el.releasePointerCapture(pointerId);
      } catch {
        /* the pointer may already be gone */
      }
    }
    pointerId = null;
    dragging = false;
    el.classList.remove("is-drag-scrolling");
  }

  function onPointerDown(e: PointerEvent) {
    // Touch and pen already pan natively; hijacking them would break that.
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    if (el.scrollWidth <= el.clientWidth) return;
    const target = e.target as Element | null;
    if (target?.closest?.(INTERACTIVE)) return;
    pointerId = e.pointerId;
    startX = e.clientX;
    startY = e.clientY;
    startScrollLeft = el.scrollLeft;
  }

  function onPointerMove(e: PointerEvent) {
    if (pointerId == null || e.pointerId !== pointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!dragging) {
      // Mostly-vertical movement is a text selection or a page scroll, not a pull.
      if (Math.abs(dx) < threshold || Math.abs(dx) <= Math.abs(dy)) return;
      dragging = true;
      el.classList.add("is-drag-scrolling");
      try {
        el.setPointerCapture(pointerId);
      } catch {
        /* capture is an optimisation, not a requirement */
      }
    }
    // Stops the browser turning the pull into a text selection.
    e.preventDefault();
    el.scrollLeft = startScrollLeft - dx;
  }

  function onPointerUp(e: PointerEvent) {
    if (pointerId == null || e.pointerId !== pointerId) return;
    if (dragging) {
      // Swallow exactly one click: the one this drag is about to produce.
      el.addEventListener("click", swallowClick, { capture: true, once: true });
    }
    reset();
  }

  function swallowClick(e: Event) {
    e.stopPropagation();
    e.preventDefault();
  }

  el.addEventListener("pointerdown", onPointerDown);
  el.addEventListener("pointermove", onPointerMove);
  el.addEventListener("pointerup", onPointerUp);
  el.addEventListener("pointercancel", onPointerUp);

  return () => {
    el.removeEventListener("pointerdown", onPointerDown);
    el.removeEventListener("pointermove", onPointerMove);
    el.removeEventListener("pointerup", onPointerUp);
    el.removeEventListener("pointercancel", onPointerUp);
    el.removeEventListener("click", swallowClick, { capture: true } as EventListenerOptions);
    reset();
  };
}
