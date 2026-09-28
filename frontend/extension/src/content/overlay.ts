/**
 * The banner the agent shows on the page it works on, with a Stop button -
 * and, once the person has taken over (takeover.ts), a Resume button.
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
  setStyles(el, styles);
  return el;
}

/**
 * Sends a message to the side panel; the content script passes
 * chrome.runtime.sendMessage, tests pass a spy. A rejected promise means
 * nobody is listening.
 */
export type PanelSender = (message: { type: "agent-stop" | "agent-takeover" | "agent-resume"; run: string }) => unknown;

/** What the banner says while the person has taken over. */
export const PAUSED_LABEL = "You took over";

/** After Stop, the side panel takes the banner off; if it cannot, the banner goes by itself after this. */
const STOP_FALLBACK_MS = 5000;

const STOPPED_KEY = "__alpharouterStoppedRuns";

/**
 * The runs stopped from a banner in this page, kept in the isolated world
 * (the page's scripts cannot reach it) and across injections of content.js.
 */
function stoppedRuns(): Set<string> {
  const scope = globalThis as typeof globalThis & { [STOPPED_KEY]?: Set<string> };
  const found = scope[STOPPED_KEY];
  if (found instanceof Set) return found;
  const fresh = new Set<string>();
  scope[STOPPED_KEY] = fresh;
  return fresh;
}

/**
 * Whether the user pressed Stop on this page's banner for run `run`. The
 * panel may already have sent an action on its way when the Stop reaches it;
 * the page refuses such an action itself.
 */
export function runStopped(run: unknown): boolean {
  return typeof run === "string" && stoppedRuns().has(run);
}

/**
 * The banner's own box, set on the element itself with priority: a page's
 * style sheet cannot hide, shrink, move or cover it (`#…{display:none
 * !important}`, a transform, opacity), since a declaration on the element
 * wins over the sheet's. Set again each time the banner is shown, in case
 * the page's script changed them.
 */
const HOST_STYLES: Styles = {
  display: "block",
  visibility: "visible",
  opacity: "1",
  // A small pill at the top centre, clear of the corners where pages put their Send, Save and chat buttons.
  position: "fixed",
  top: "8px",
  left: "50%",
  right: "auto",
  bottom: "auto",
  width: "auto",
  height: "auto",
  transform: "translateX(-50%)",
  filter: "none",
  "clip-path": "none",
  // Only its buttons take the pointer: a click anywhere else on it reaches the page beneath.
  "pointer-events": "none",
  "z-index": "2147483647",
  margin: "0",
  padding: "0",
  border: "0",
  background: "transparent",
};

function setStyles(el: HTMLElement, styles: Styles): void {
  for (const [name, value] of Object.entries(styles)) el.style.setProperty(name, value, "important");
}

type Host = HTMLElement & { __label?: HTMLElement; __resume?: HTMLButtonElement; __working?: string };

/**
 * Show (or update) the banner for run `run`; Stop sends `agent-stop` for that
 * run, and Resume - shown only while the person has taken over - calls
 * `onResume`. The panel shows the banner with every action, so a banner the
 * page removed comes back; while paused, a new label is kept for later and
 * the banner goes on saying the person took over.
 */
export function showOverlay(doc: Document, run: string, label: string, send: PanelSender, onResume?: () => void): void {
  // A run stopped here does not come back on this page.
  if (runStopped(run)) return;
  let host = doc.getElementById(OVERLAY_ID) as Host | null;
  if (host && host.dataset.run !== run) {
    host.remove();
    host = null;
  }
  if (host) {
    setStyles(host, HOST_STYLES);
    host.__working = label;
    if (host.__label && host.dataset.paused !== "1") host.__label.textContent = label;
    return;
  }
  const root = doc.body ?? doc.documentElement;
  host = styled(doc, "div", HOST_STYLES) as Host;
  host.id = OVERLAY_ID;
  host.dataset.run = run;
  host.__working = label;
  const shadow = host.attachShadow({ mode: "closed" });
  const box = styled(doc, "div", {
    display: "flex",
    "align-items": "center",
    gap: "10px",
    padding: "4px 6px 4px 12px",
    "border-radius": "999px",
    background: "rgba(31, 36, 48, 0.92)",
    color: "#ffffff",
    font: "12px/1.3 system-ui, -apple-system, 'Segoe UI', sans-serif",
    "box-shadow": "0 2px 10px rgba(0, 0, 0, 0.25)",
    "max-width": "320px",
    "pointer-events": "none",
  });
  box.setAttribute("role", "status");
  const text = styled(doc, "span", { overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" });
  text.textContent = label;
  const buttonStyles: Styles = {
    cursor: "pointer",
    padding: "3px 10px",
    border: "0",
    "border-radius": "999px",
    color: "#ffffff",
    font: "600 12px/1.3 system-ui, -apple-system, 'Segoe UI', sans-serif",
    "pointer-events": "auto",
  };
  // Resume: only while the person has taken over; the watch (takeover.ts) shows and hides it.
  const resume = styled(doc, "button", { ...buttonStyles, background: "#2eaadc", display: "none" });
  resume.type = "button";
  // Out of the page's Tab order: a Tab from the page's last field must not land here, where Enter would act.
  resume.tabIndex = -1;
  resume.textContent = "Resume";
  resume.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    onResume?.();
  });
  const stop = styled(doc, "button", { ...buttonStyles, background: "#e5484d" });
  stop.type = "button";
  stop.tabIndex = -1;
  stop.textContent = "Stop";
  stop.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    text.textContent = "Stopping…";
    stop.disabled = true;
    stoppedRuns().add(run);
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
  box.append(text, resume, stop);
  shadow.append(box);
  host.__label = text;
  host.__resume = resume;
  root.append(host);
}

/**
 * The person took over (`paused`), or is done: the banner says so and shows
 * Resume, or goes back to what the panel last had it say.
 */
export function setOverlayPaused(doc: Document, run: string, paused: boolean): void {
  const host = doc.getElementById(OVERLAY_ID) as Host | null;
  if (!host || host.dataset.run !== run) return;
  if (paused) host.dataset.paused = "1";
  else delete host.dataset.paused;
  if (host.__label) host.__label.textContent = paused ? PAUSED_LABEL : (host.__working ?? "");
  if (host.__resume) setStyles(host.__resume, { display: paused ? "inline-block" : "none" });
}

/** Veil the banner for a screenshot, as the visual layer is: the model sees the page, not Alpharouter's own controls. */
export function veilOverlay(doc: Document, veiled: boolean): void {
  const host = doc.getElementById(OVERLAY_ID);
  if (host) setStyles(host, { visibility: veiled ? "hidden" : "visible" });
}

export function hideOverlay(doc: Document, run?: string): void {
  const host = doc.getElementById(OVERLAY_ID);
  if (host && (run === undefined || host.dataset.run === run)) host.remove();
}
