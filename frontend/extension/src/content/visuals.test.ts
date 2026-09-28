/**
 * @vitest-environment happy-dom
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  hideTarget,
  hideVisuals,
  highlightState,
  moveCursor,
  pulseClick,
  setHighlightState,
  showTarget,
  showVisuals,
  veilVisuals,
  VISUALS_ID,
} from "./visuals";

type Parts = { frame: HTMLElement; cursor: SVGSVGElement; target: HTMLElement };
const parts = (): Parts => (document.getElementById(VISUALS_ID) as unknown as { __parts: Parts }).__parts;

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("showVisuals", () => {
  it("adds one host with a closed shadow root and starts in the working state", () => {
    const host = showVisuals(document);
    expect(document.getElementById(VISUALS_ID)).toBe(host);
    expect(host.style.getPropertyValue("pointer-events")).toBe("none");
    expect(parts().frame.dataset.state).toBe("working");
    // A second call does not add a second host.
    showVisuals(document);
    expect(document.querySelectorAll(`#${VISUALS_ID}`)).toHaveLength(1);
  });
});

describe("setHighlightState", () => {
  it("colours the border per state and records it", () => {
    showVisuals(document);
    setHighlightState(document, "waiting");
    expect(parts().frame.dataset.state).toBe("waiting");
    expect(parts().frame.style.getPropertyValue("box-shadow")).toContain("255, 179, 71");
    setHighlightState(document, "error");
    expect(parts().frame.style.getPropertyValue("box-shadow")).toContain("229, 72, 77");
  });

  it("does nothing without a layer", () => {
    expect(() => setHighlightState(document, "paused")).not.toThrow();
  });
});

describe("moveCursor", () => {
  it("translates the cursor to the point", () => {
    showVisuals(document);
    moveCursor(document, { x: 120, y: 80 });
    expect(parts().cursor.style.getPropertyValue("transform")).toBe("translate(120px, 80px)");
  });
});

describe("target box", () => {
  it("shows at a rect and hides", () => {
    showVisuals(document);
    showTarget(document, { x: 10, y: 20, width: 100, height: 40 });
    const target = parts().target;
    expect(target.style.getPropertyValue("display")).toBe("block");
    expect(target.style.getPropertyValue("left")).toBe("10px");
    expect(target.style.getPropertyValue("width")).toBe("100px");
    hideTarget(document);
    expect(target.style.getPropertyValue("display")).toBe("none");
  });
});

describe("pulseClick", () => {
  it("does not throw and cleans up when the DOM has no animation support", () => {
    showVisuals(document);
    expect(() => pulseClick(document, { x: 5, y: 5 }, "double")).not.toThrow();
  });
});

describe("veilVisuals", () => {
  it("hides the whole layer for a capture and shows it again", () => {
    const host = showVisuals(document);
    veilVisuals(document, true);
    expect(host.style.getPropertyValue("visibility")).toBe("hidden");
    veilVisuals(document, false);
    expect(host.style.getPropertyValue("visibility")).toBe("visible");
  });
});

describe("hideVisuals", () => {
  it("removes the host", () => {
    showVisuals(document);
    hideVisuals(document);
    expect(document.getElementById(VISUALS_ID)).toBeNull();
  });
});

describe("the layer on a page the agent reached later", () => {
  it("comes up with the border, the cursor or the target, on a page that had none", async () => {
    const { runAgentCall } = await import("./runtime");
    const { isRendered } = await import("./extract");
    // A fresh page after a navigation: no layer yet.
    hideVisuals(document);
    expect(document.getElementById(VISUALS_ID)).toBeNull();
    await runAgentCall(document, "visuals_state", { state: "waiting" }, isRendered, () => undefined);
    expect(document.getElementById(VISUALS_ID)).not.toBeNull();
    expect(highlightState(document)).toBe("waiting");
    hideVisuals(document);
    await runAgentCall(document, "visuals_cursor", { x: 10, y: 20 }, isRendered, () => undefined);
    expect(document.getElementById(VISUALS_ID)).not.toBeNull();
    hideVisuals(document);
    await runAgentCall(document, "visuals_target", { rect: { x: 1, y: 2, width: 3, height: 4 } }, isRendered, () => undefined);
    expect(document.getElementById(VISUALS_ID)).not.toBeNull();
  });
});
