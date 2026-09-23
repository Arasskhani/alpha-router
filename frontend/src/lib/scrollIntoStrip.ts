/**
 * Scroll a horizontal strip (tabs, filter chips) just enough to show `item`.
 *
 * On a phone these strips scroll sideways instead of wrapping. When the page
 * selects an item by itself it may be out of view; `scrollIntoView` would do
 * it, but may also scroll the page and any clipped ancestor around the strip.
 * This moves only the strip, by the amount the item is out of view, left to
 * right and right to left alike, and does nothing where the item already fits.
 */
export function scrollIntoStrip(strip: HTMLElement | null, item: HTMLElement | null | undefined): void {
  if (!strip || !item) return;
  const outer = strip.getBoundingClientRect();
  const inner = item.getBoundingClientRect();
  if (inner.left < outer.left) strip.scrollLeft -= outer.left - inner.left;
  else if (inner.right > outer.right) strip.scrollLeft += inner.right - outer.right;
}
