/**
 * When the person takes over the page the agent is working on.
 *
 * Under full control the agent's clicks and keys arrive as trusted events, the
 * kind a page cannot tell from a person's - and neither can this script. So
 * the panel tells the page when its own input is going out (a dispatch
 * window), and a trusted press, key or wheel outside such a window is the
 * person's: they took over. The page then pauses itself at once - the banner
 * says so and offers Resume, the border turns grey, and every action the panel
 * may still have on its way is refused - and tells the panel, which holds the
 * run at its next step until Resume, from the banner or from the panel.
 *
 * Without full control the agent's events are synthetic (never trusted), so no
 * window is needed and every trusted event is the person's.
 *
 * A wheel event can reach the page after its window has closed: Chrome
 * answers the agent's scroll once the compositor has it, and the page's
 * (passive) listeners run later, on the page's own thread. So a wheel event
 * shortly after the agent's own input is still counted as the agent's; a
 * press or a key is not, as those reach the page before Chrome answers.
 *
 * The state lives on the isolated world's global, like the stopped runs: the
 * panel injects content.js before every call, and a new copy must find the
 * watch the last one set up rather than add a second one.
 */

import { runStopped, setOverlayPaused } from "./overlay";
import { isOwnHost } from "./own";
import { highlightState, setHighlightState, type HighlightState } from "./visuals";

type TakeoverMessage = { type: "agent-takeover"; run: string } | { type: "agent-resume"; run: string };
export type TakeoverSender = (message: TakeoverMessage) => unknown;

type Watch = {
  run: string;
  /** The panel's own input is going out: trusted events now are the agent's. */
  dispatching: boolean;
  /** Until when a wheel event is still the agent's own, once its input is out (a time from Date.now). */
  wheelsUntil: number;
  /** The person took over; nothing is done on the page until Resume. */
  paused: boolean;
  /** What the border showed before the pause, to show again after it. */
  before: HighlightState | null;
  send: TakeoverSender;
  stop: () => void;
};

const WATCH_KEY = "__alpharouterTakeover";

/** What a person does that counts as taking over: a press, a key, a wheel. Moving the mouse does not. */
const EVENTS = ["pointerdown", "keydown", "wheel"] as const;

/** How long after the agent's own input a wheel event is still counted as the agent's. */
const WHEEL_GRACE_MS = 1000;

function scope(): { [WATCH_KEY]?: Watch } {
  return globalThis as typeof globalThis & { [WATCH_KEY]?: Watch };
}

function current(): Watch | undefined {
  const watch = scope()[WATCH_KEY];
  return watch && typeof watch === "object" ? watch : undefined;
}

/** An event on the agent's own banner or layer - Stop, Resume - is not a take-over. */
function onOwnUi(event: Event): boolean {
  const path = typeof event.composedPath === "function" ? event.composedPath() : [];
  return path.some((node) => node instanceof Element && isOwnHost(node));
}

/** Whether run `run` is paused on this page because the person took over. */
export function runPaused(run: unknown): boolean {
  const watch = current();
  return Boolean(watch && watch.paused && typeof run === "string" && watch.run === run);
}

/** Send best-effort: a panel that is gone is not this page's problem. */
function tell(watch: Watch, message: TakeoverMessage): void {
  try {
    Promise.resolve(watch.send(message)).catch(() => undefined);
  } catch {
    // Nobody listening.
  }
}

function pause(doc: Document, watch: Watch): void {
  if (watch.paused) return;
  // Stopped from the banner: the run is over, and there is nothing to pause.
  if (runStopped(watch.run)) {
    watch.stop();
    return;
  }
  watch.paused = true;
  watch.dispatching = false;
  watch.before = highlightState(doc);
  setOverlayPaused(doc, watch.run, true);
  setHighlightState(doc, "paused");
  tell(watch, { type: "agent-takeover", run: watch.run });
}

/**
 * Watch this page for run `run`, or keep the watch already up for it. A
 * watch for another run is replaced: the old run's pause goes with it.
 */
export function watchTakeover(doc: Document, run: string, send: TakeoverSender): void {
  const existing = current();
  if (existing?.run === run) {
    existing.send = send;
    return;
  }
  existing?.stop();
  const view = doc.defaultView;
  if (!view) return;
  const watch: Watch = { run, dispatching: false, wheelsUntil: 0, paused: false, before: null, send, stop: () => undefined };
  const onInput = (event: Event) => {
    if (!event.isTrusted || watch.dispatching || watch.paused || onOwnUi(event)) return;
    if (event.type === "wheel" && Date.now() < watch.wheelsUntil) return;
    pause(doc, watch);
  };
  // Capture, so a page that stops propagation still shows the take-over; passive, so scrolling is not held up.
  for (const name of EVENTS) view.addEventListener(name, onInput, { capture: true, passive: true });
  watch.stop = () => {
    for (const name of EVENTS) view.removeEventListener(name, onInput, { capture: true });
    if (scope()[WATCH_KEY] === watch) delete scope()[WATCH_KEY];
  };
  scope()[WATCH_KEY] = watch;
}

/** Take the watch off (the run ended, or left this page). */
export function stopWatching(run?: unknown): void {
  const watch = current();
  if (!watch || (run !== undefined && watch.run !== run)) return;
  watch.stop();
}

/**
 * The panel's own input is about to go out (`on`), or has (`off`). Answers
 * whether the page is paused: paused, the panel sends nothing.
 */
export function setDispatching(on: boolean): { paused: boolean } {
  const watch = current();
  if (!watch) return { paused: false };
  // Closing the window: a wheel event of the agent's own may still be on its way.
  if (watch.dispatching && !on) watch.wheelsUntil = Date.now() + WHEEL_GRACE_MS;
  watch.dispatching = on && !watch.paused;
  return { paused: watch.paused };
}

/**
 * The person is done: from Resume on the banner (`tellPanel`), or from the
 * panel, which already knows. The watch is armed again.
 */
export function resumeTakeover(doc: Document, run: unknown, tellPanel: boolean): boolean {
  const watch = current();
  if (!watch || !watch.paused || (run !== undefined && watch.run !== run)) return false;
  watch.paused = false;
  setOverlayPaused(doc, watch.run, false);
  setHighlightState(doc, watch.before ?? "working");
  watch.before = null;
  if (tellPanel) tell(watch, { type: "agent-resume", run: watch.run });
  return true;
}
