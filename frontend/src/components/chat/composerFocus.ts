/**
 * What in the composer box keeps a tap: controls, and the queued messages and
 * attachments above the field, whose text can be selected and whose tap should
 * not bring a phone's keyboard up. The box itself is role="presentation".
 */
const OWN_TAP =
  'button, a[href], input, select, textarea, label, summary, [contenteditable], [role]:not([role="presentation"], [role="none"]), .alpha-router-prompt-queue, .alpha-router-pending-attachments';

/**
 * A tap in the composer box on nothing that keeps a tap of its own - the
 * box's padding, the space around the bar's buttons - goes to the message
 * field. The box looks like one field, and on a phone the field itself is a
 * single 22px line in it.
 *
 * For the box's mousedown and click; `currentTarget` is the box, and only
 * what is inside it counts (a role on the page around the box does not). On
 * mousedown the default is prevented, so a mouse does not take focus away
 * from the field again, or out of it while typing. A finger's tap can move
 * focus by itself after the mousedown; the click that follows brings it back
 * to the field. Returns whether the tap went to the field.
 */
export function focusFieldOnBoxTap(
  event: {
    type: string;
    target: EventTarget | null;
    currentTarget: EventTarget | null;
    preventDefault(): void;
  },
  field: HTMLTextAreaElement | null,
): boolean {
  const { target, currentTarget: box } = event;
  if (
    !field ||
    field.disabled ||
    !(target instanceof Element) ||
    !(box instanceof Element)
  )
    return false;
  const own = target.closest(OWN_TAP);
  if (own && own !== box && box.contains(own)) return false;
  if (event.type === "mousedown") event.preventDefault();
  field.focus();
  return true;
}
