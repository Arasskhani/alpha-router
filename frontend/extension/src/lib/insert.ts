/**
 * Putting an answer into the page: into the field the user left focused in
 * the tab next to the panel - a text box, a text area, or an editor
 * (contenteditable) - where they could have pasted it themselves.
 *
 * Never into a password, card or one-time-code field, and only on the site
 * the panel saw: the function checks that again inside the page. It types
 * through the field's own setter and fires the events a keystroke would, so
 * pages built with React and the like see the change.
 */

export type InsertResult = "inserted" | "no_field" | "sensitive" | "moved";

/**
 * Runs inside the page (chrome.scripting serializes it): it may use nothing
 * from this module, so everything it needs is written out here.
 */
export function insertIntoFocusedField(text: string, host: string): InsertResult {
  if (location.hostname.replace(/\.$/, "") !== host) return "moved";
  let el: Element | null = document.activeElement;
  // Follow focus into frames of the same site; another site's frame is out of reach.
  while (el && (el.tagName === "IFRAME" || el.tagName === "FRAME")) {
    let inner: Element | null = null;
    try {
      inner = (el as HTMLIFrameElement).contentDocument?.activeElement ?? null;
    } catch {
      inner = null;
    }
    if (!inner) return "no_field";
    el = inner;
  }
  if (!el || el === document.body || el === document.documentElement) return "no_field";

  const describe = [el.getAttribute("type"), el.getAttribute("name"), el.id, el.getAttribute("autocomplete"), el.getAttribute("aria-label")]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const sensitive =
    /\b(password|passwd|pwd|pin|cvv|cvc|csc|iban|otp)\b/.test(describe) ||
    /(^|[\s_-])cc-|\bcard|security.?code|one-time-code|current-password|new-password/.test(describe);

  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") {
    const field = el as HTMLInputElement | HTMLTextAreaElement;
    const type = tag === "INPUT" ? (field.getAttribute("type") || "text").toLowerCase() : "textarea";
    if (type === "password" || sensitive) return "sensitive";
    if (!["text", "search", "email", "url", "tel", "textarea"].includes(type)) return "no_field";
    if (field.disabled || field.readOnly) return "no_field";
    const insert = tag === "INPUT" ? text.replace(/\s*\n\s*/g, " ") : text;
    let start = field.value.length;
    let end = start;
    try {
      start = field.selectionStart ?? start;
      end = field.selectionEnd ?? start;
    } catch {
      // Email and URL fields have no selection: the text goes at the end.
    }
    let next = field.value.slice(0, start) + insert + field.value.slice(end);
    if (field.maxLength > 0) next = next.slice(0, field.maxLength);
    const proto = tag === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setValue = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setValue) setValue.call(field, next);
    else field.value = next;
    try {
      const caret = Math.min(start + insert.length, next.length);
      field.setSelectionRange(caret, caret);
    } catch {
      // No selection to move.
    }
    field.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: insert }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
    return "inserted";
  }

  if ((el as HTMLElement).isContentEditable) {
    if (sensitive) return "sensitive";
    const editor = el as HTMLElement;
    const doc = editor.ownerDocument;
    // The editor's own way first: it keeps undo and the editor's model in step.
    const typed = typeof doc.execCommand === "function" && doc.execCommand("insertText", false, text);
    if (!typed) {
      const selection = doc.getSelection();
      const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
      const node = doc.createTextNode(text);
      if (range && editor.contains(range.commonAncestorContainer)) {
        range.deleteContents();
        range.insertNode(node);
        range.setStartAfter(node);
        range.collapse(true);
        selection?.removeAllRanges();
        selection?.addRange(range);
      } else {
        editor.append(node);
      }
      editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    }
    return "inserted";
  }
  return "no_field";
}

/**
 * An answer as plain text for a form: the markdown marks go, the words and
 * line breaks stay. Links keep their address in brackets.
 */
export function plainText(markdown: string): string {
  return markdown
    .replace(/^```[^\n]*\n([\s\S]*?)\n?```$/gm, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, "$1 ($2)")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2")
    .replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?!\*)/g, "$1$2")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
