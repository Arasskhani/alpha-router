/**
 * The elements Alpharouter puts on a page - the banner with Stop, and the
 * border, cursor and target box of full control - told apart from the page's.
 *
 * By the element the extension made, not by its id: a page can give one of
 * its own elements the banner's id, which would then be left out of the
 * outline and of find, taken for the banner by describe_at, and a person's
 * click in it would not count as taking over. The set lives in the content
 * script's isolated world, where the page cannot reach it, and survives a
 * second injection of content.js into the same document.
 */

const OWN_KEY = "__alpharouterOwnHosts";

function ownHosts(): WeakSet<Element> {
  const scope = globalThis as typeof globalThis & { [OWN_KEY]?: WeakSet<Element> };
  const found = scope[OWN_KEY];
  if (found instanceof WeakSet) return found;
  const fresh = new WeakSet<Element>();
  scope[OWN_KEY] = fresh;
  return fresh;
}

/** Say that the extension made `host`. */
export function markOwn(host: Element): void {
  ownHosts().add(host);
}

/** Whether the extension made `el` itself. */
export function isOwnHost(el: Element): boolean {
  return ownHosts().has(el);
}

/** The element with `id` that the extension made, if there is one: never a page's element that took the same id. */
export function ownHost<T extends Element = HTMLElement>(doc: Document, id: string): T | null {
  const byId = doc.getElementById(id);
  if (byId && isOwnHost(byId)) return byId as unknown as T;
  const found = Array.from(doc.querySelectorAll(`[id="${id}"]`)).find(isOwnHost);
  return (found as unknown as T | undefined) ?? null;
}

/** Whether `el` is one of the extension's elements or sits inside one, across shadow roots (closed ones too). */
export function inOwnUi(el: Element | null): boolean {
  for (let node = el, depth = 0; node && depth < 80; depth += 1) {
    if (isOwnHost(node)) return true;
    if (node.parentElement) node = node.parentElement;
    else {
      const root = node.getRootNode();
      node = root instanceof ShadowRoot ? root.host : null;
    }
  }
  return false;
}
