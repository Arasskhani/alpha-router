/**
 * The banner the agent shows on the page it works on, with a Stop button.
 *
 * A person watching the page sees that Alpharouter is acting on it and can
 * stop it from right there. The banner lives in a closed shadow root, so the
 * page's scripts cannot read or restyle what is inside, and it is styled
 * through the CSSOM only: a page's Content-Security-Policy can refuse
 * injected <style> elements and style attributes, never style properties set
 * from script. Stop tells the side panel through the extension's own
 * messaging, which the page cannot reach.
 */

export const OVERLAY_ID = "alpharouter-agent-overlay";

type Styles = Record<string, string>;

function styled<K extends keyof HTMLElementTagNameMap>(doc: Document, tag: K, styles: Styles): HTMLElementTagNameMap[K] {
  const el = doc.createElement(tag);
  for (const [name, value] of Object.entries(styles)) el.style.setProperty(name, value, "important");
  return el;
}

/**
 * Sends the stop request; the content script passes chrome.runtime.sendMessage,
 * tests pass a spy. A rejected promise means nobody is listening.
 */
export type StopSender = (message: { type: "agent-stop"; run: string }) => unknown;

/** After Stop, the side panel takes the banner off; if it cannot, the banner goes by itself after this. */
const STOP_FALLBACK_MS = 5000;

/** Show (or update) the banner for run `run`; Stop sends `agent-stop` for that run. */
export function showOverlay(doc: Document, run: string, label: string, send: StopSender): void {
  let host = doc.getElementById(OVERLAY_ID);
  if (host && host.dataset.run !== run) {
    host.remove();
    host = null;
  }
  if (host) {
    const text = (host as HTMLElement & { __label?: HTMLElement }).__label;
    if (text) text.textContent = label;
    return;
  }
  const root = doc.body ?? doc.documentElement;
  host = styled(doc, "div", {
    position: "fixed",
    right: "16px",
    bottom: "16px",
    "z-index": "2147483647",
    margin: "0",
    padding: "0",
    border: "0",
    background: "transparent",
  });
  host.id = OVERLAY_ID;
  host.dataset.run = run;
  const shadow = host.attachShadow({ mode: "closed" });
  const box = styled(doc, "div", {
    display: "flex",
    "align-items": "center",
    gap: "10px",
    padding: "8px 10px 8px 12px",
    "border-radius": "10px",
    background: "#1f2430",
    color: "#ffffff",
    font: "13px/1.3 system-ui, -apple-system, 'Segoe UI', sans-serif",
    "box-shadow": "0 4px 16px rgba(0, 0, 0, 0.3)",
    "max-width": "360px",
  });
  box.setAttribute("role", "status");
  const text = styled(doc, "span", { overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" });
  text.textContent = label;
  const stop = styled(doc, "button", {
    cursor: "pointer",
    padding: "4px 10px",
    border: "0",
    "border-radius": "6px",
    background: "#e5484d",
    color: "#ffffff",
    font: "600 12px/1.3 system-ui, -apple-system, 'Segoe UI', sans-serif",
  });
  stop.type = "button";
  stop.textContent = "Stop";
  stop.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    text.textContent = "Stopping…";
    stop.disabled = true;
    doc.defaultView?.setTimeout(() => hideOverlay(doc, run), STOP_FALLBACK_MS);
    // Nobody listening - the side panel was closed, so the run is already over: the banner just goes.
    let sent: unknown;
    try {
      sent = send({ type: "agent-stop", run });
    } catch {
      hideOverlay(doc, run);
      return;
    }
    Promise.resolve(sent).catch(() => hideOverlay(doc, run));
  });
  box.append(text, stop);
  shadow.append(box);
  (host as HTMLElement & { __label?: HTMLElement }).__label = text;
  root.append(host);
}

export function hideOverlay(doc: Document, run?: string): void {
  const host = doc.getElementById(OVERLAY_ID);
  if (host && (run === undefined || host.dataset.run === run)) host.remove();
}
