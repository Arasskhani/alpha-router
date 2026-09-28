/**
 * What a person sees while the agent works a page: a glowing border, a virtual
 * cursor that moves to each target, and an outline around what it is about to
 * act on. It lives beside the Stop banner (overlay.ts) and follows the same
 * rules: a closed shadow root the page's scripts cannot read, styled only
 * through the CSSOM and the Web Animations API, so a page's Content-Security-Policy
 * (which can refuse an injected <style> or a style attribute, never a property
 * set from script) cannot hide or move it. It never takes pointer events, so it
 * is invisible to the agent's own input and to the person's.
 *
 * The panel drives it in step with the real CDP input: before a click it shows
 * the target and moves the cursor there, and it sets the highlight to match what
 * the run is doing (working, waiting for an approval, paused, an error).
 */

import { markOwn, ownHost } from "./own";

export const VISUALS_ID = "alpharouter-agent-visuals";

export type HighlightState = "working" | "waiting" | "paused" | "error";
export type ClickKind = "left" | "right" | "double" | "triple";
export type Point = { x: number; y: number };
export type Rect = { x: number; y: number; width: number; height: number };

type Styles = Record<string, string>;

const STATE_COLOR: Record<HighlightState, string> = {
  working: "rgba(46, 170, 220, 0.9)", // brand cyan
  waiting: "rgba(255, 179, 71, 0.95)", // amber
  paused: "rgba(150, 150, 150, 0.8)", // grey
  error: "rgba(229, 72, 77, 0.95)", // red
};

function setStyles(el: HTMLElement | SVGElement, styles: Styles): void {
  for (const [name, value] of Object.entries(styles)) el.style.setProperty(name, value, "important");
}

/** The host's own box: fixed over the whole viewport, above everything, click-through. */
const HOST_STYLES: Styles = {
  position: "fixed",
  inset: "0",
  margin: "0",
  padding: "0",
  border: "0",
  width: "100%",
  height: "100%",
  "pointer-events": "none",
  "z-index": "2147483646", // just below the Stop banner
  background: "transparent",
  display: "block",
  visibility: "visible",
  opacity: "1",
  transform: "none",
  filter: "none",
  "clip-path": "none",
};

type Parts = { frame: HTMLElement; cursor: SVGSVGElement; target: HTMLElement };

function reducedMotion(doc: Document): boolean {
  try {
    return doc.defaultView?.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  } catch {
    return false;
  }
}

function buildParts(doc: Document, shadow: ShadowRoot): Parts {
  const frame = doc.createElement("div");
  setStyles(frame, {
    position: "absolute",
    inset: "0",
    "pointer-events": "none",
    "box-shadow": "inset 0 0 0 3px rgba(46, 170, 220, 0.9)",
    transition: "box-shadow 160ms ease",
  });

  const target = doc.createElement("div");
  setStyles(target, {
    position: "absolute",
    "pointer-events": "none",
    border: "2px solid rgba(46, 170, 220, 0.95)",
    "border-radius": "4px",
    "box-shadow": "0 0 0 2px rgba(255, 255, 255, 0.6)",
    display: "none",
    left: "0",
    top: "0",
    width: "0",
    height: "0",
  });

  const cursor = doc.createElementNS("http://www.w3.org/2000/svg", "svg") as SVGSVGElement;
  cursor.setAttribute("width", "22");
  cursor.setAttribute("height", "22");
  cursor.setAttribute("viewBox", "0 0 22 22");
  const path = doc.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M2 2 L2 17 L6.5 12.8 L9.4 19 L12 17.8 L9.1 11.8 L15 11.6 Z");
  path.setAttribute("fill", "#111");
  path.setAttribute("stroke", "#fff");
  path.setAttribute("stroke-width", "1.4");
  cursor.append(path);
  setStyles(cursor, {
    position: "absolute",
    left: "0",
    top: "0",
    "pointer-events": "none",
    transform: "translate(-100px, -100px)",
    transition: "transform 220ms cubic-bezier(0.22, 0.61, 0.36, 1)",
    "will-change": "transform",
    filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))",
  });

  shadow.append(frame, target, cursor);
  return { frame, cursor, target };
}

type Host = HTMLElement & { __parts?: Parts; __pulse?: { cancel: () => void } };

/** Show the layer for a fresh run, or return the one already up. */
export function showVisuals(doc: Document): Host {
  const existing = ownHost<Host>(doc, VISUALS_ID);
  if (existing) {
    setStyles(existing, HOST_STYLES);
    return existing;
  }
  const host = doc.createElement("div") as Host;
  host.id = VISUALS_ID;
  markOwn(host);
  setStyles(host, HOST_STYLES);
  const shadow = host.attachShadow({ mode: "closed" });
  host.__parts = buildParts(doc, shadow);
  (doc.body ?? doc.documentElement).append(host);
  setHighlightState(doc, "working");
  return host;
}

/** Veil the layer for a capture, so the model never sees the cursor or the border; unveil after. */
export function veilVisuals(doc: Document, veiled: boolean): void {
  const host = ownHost<Host>(doc, VISUALS_ID);
  if (host) setStyles(host, { visibility: veiled ? "hidden" : "visible" });
}

export function hideVisuals(doc: Document): void {
  const host = ownHost<Host>(doc, VISUALS_ID);
  host?.__pulse?.cancel();
  host?.remove();
}

/** The highlight's state now, or null when the layer is not up. */
export function highlightState(doc: Document): HighlightState | null {
  const state = (ownHost<Host>(doc, VISUALS_ID))?.__parts?.frame.dataset.state;
  return state && state in STATE_COLOR ? (state as HighlightState) : null;
}

export function setHighlightState(doc: Document, state: HighlightState): void {
  const host = ownHost<Host>(doc, VISUALS_ID);
  const frame = host?.__parts?.frame;
  if (!host || !frame) return;
  const color = STATE_COLOR[state];
  setStyles(frame, { "box-shadow": `inset 0 0 0 3px ${color}` });
  frame.dataset.state = state;
  host.__pulse?.cancel();
  host.__pulse = undefined;
  // A gentle pulse while working or waiting; a steady border when paused or in error.
  if ((state === "working" || state === "waiting") && typeof frame.animate === "function" && !reducedMotion(doc)) {
    const animation = frame.animate([{ opacity: 1 }, { opacity: 0.45 }, { opacity: 1 }], {
      duration: 1600,
      iterations: Infinity,
    });
    // cancel() rejects the finished promise; we never await it, so swallow it.
    (animation as { finished?: Promise<unknown> }).finished?.catch(() => {});
    host.__pulse = { cancel: () => animation.cancel() };
  } else {
    setStyles(frame, { opacity: "1" });
  }
}

/** Move the cursor to a viewport point; instant when the person prefers reduced motion. */
export function moveCursor(doc: Document, point: Point): void {
  const cursor = (ownHost<Host>(doc, VISUALS_ID))?.__parts?.cursor;
  if (!cursor) return;
  setStyles(cursor, { transition: reducedMotion(doc) ? "none" : "transform 220ms cubic-bezier(0.22, 0.61, 0.36, 1)" });
  setStyles(cursor, { transform: `translate(${point.x}px, ${point.y}px)` });
}

/** A brief ripple where a click lands (double and triple clicks ripple twice/thrice). */
export function pulseClick(doc: Document, point: Point, kind: ClickKind = "left"): void {
  const host = ownHost<Host>(doc, VISUALS_ID);
  const shadow = (host as unknown as { shadowRoot?: ShadowRoot })?.shadowRoot;
  const parent = host?.__parts?.cursor.parentNode ?? shadow ?? null;
  if (!host || !parent) return;
  const ripple = doc.createElement("div");
  const color = kind === "right" ? "rgba(255,179,71,0.9)" : "rgba(46,170,220,0.9)";
  setStyles(ripple, {
    position: "absolute",
    left: `${point.x - 10}px`,
    top: `${point.y - 10}px`,
    width: "20px",
    height: "20px",
    "border-radius": "50%",
    border: `2px solid ${color}`,
    "pointer-events": "none",
  });
  parent.appendChild(ripple);
  const done = () => ripple.remove();
  if (typeof ripple.animate === "function") {
    const rings = kind === "triple" ? 3 : kind === "double" ? 2 : 1;
    const animation = ripple.animate([{ transform: "scale(0.4)", opacity: 1 }, { transform: "scale(1.6)", opacity: 0 }], {
      duration: 420,
      iterations: rings,
    });
    (animation as { finished?: Promise<unknown> }).finished?.then(done, done);
  } else {
    done();
  }
}

export function showTarget(doc: Document, rect: Rect): void {
  const target = (ownHost<Host>(doc, VISUALS_ID))?.__parts?.target;
  if (!target) return;
  setStyles(target, {
    display: "block",
    left: `${rect.x}px`,
    top: `${rect.y}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
  });
}

export function hideTarget(doc: Document): void {
  const target = (ownHost<Host>(doc, VISUALS_ID))?.__parts?.target;
  if (target) setStyles(target, { display: "none" });
}
