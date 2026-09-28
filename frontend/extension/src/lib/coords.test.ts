import { describe, expect, it } from "vitest";

import {
  clampMaxSide,
  clampToViewport,
  cssToFrame,
  cssViewportFromMetrics,
  DEFAULT_MAX_SIDE,
  frameFor,
  frameToCss,
} from "./coords";
import { layoutMetrics } from "../test/cdpFixtures";

describe("frameFor", () => {
  it("scales a large viewport down to the longest side", () => {
    const frame = frameFor({ width: 2560, height: 1440 }, 1280);
    expect(frame.scale).toBe(0.5);
    expect(frame).toMatchObject({ width: 1280, height: 720 });
  });

  it("never scales a small viewport up", () => {
    const frame = frameFor({ width: 800, height: 600 }, 1280);
    expect(frame.scale).toBe(1);
    expect(frame).toMatchObject({ width: 800, height: 600 });
  });

  it("scales by height when the page is taller than it is wide", () => {
    const frame = frameFor({ width: 600, height: 2000 }, 1000);
    expect(frame.scale).toBe(0.5);
    expect(frame).toMatchObject({ width: 300, height: 1000 });
  });

  it("uses the default max side", () => {
    expect(frameFor({ width: 3000, height: 1000 }).width).toBe(DEFAULT_MAX_SIDE);
  });
});

describe("round trip", () => {
  it("frame → css → frame is the identity at any scale", () => {
    for (const css of [{ width: 2560, height: 1440 }, { width: 1000, height: 3000 }, { width: 800, height: 600 }]) {
      const frame = frameFor(css, 1280);
      const p = { x: 300, y: 200 };
      const back = cssToFrame(frameToCss(p, frame), frame);
      expect(back.x).toBeCloseTo(p.x, 6);
      expect(back.y).toBeCloseTo(p.y, 6);
    }
  });

  it("maps a frame point to the matching css pixel at scale 0.5", () => {
    const frame = frameFor({ width: 2560, height: 1440 }, 1280);
    expect(frameToCss({ x: 640, y: 360 }, frame)).toEqual({ x: 1280, y: 720 });
  });
});

describe("clampToViewport", () => {
  it("keeps a point inside", () => {
    expect(clampToViewport({ x: 5000, y: -3 }, { width: 800, height: 600 })).toEqual({ x: 799, y: 0 });
  });
});

describe("clampMaxSide", () => {
  it("bounds the value and falls back on nonsense", () => {
    expect(clampMaxSide(1600)).toBe(1600);
    expect(clampMaxSide(50)).toBe(400);
    expect(clampMaxSide(99999)).toBe(4096);
    expect(clampMaxSide(undefined)).toBe(DEFAULT_MAX_SIDE);
    expect(clampMaxSide(Number.NaN)).toBe(DEFAULT_MAX_SIDE);
  });
});

describe("cssViewportFromMetrics", () => {
  it("reads the size Chromium reports, at any display scale", () => {
    expect(cssViewportFromMetrics(layoutMetrics({ width: 870, height: 968 }))).toEqual({ width: 870, height: 968 });
    // At 150 %: the CSS viewport, not the device pixels of the deprecated fields.
    expect(cssViewportFromMetrics(layoutMetrics({ width: 870.6666870117188, height: 968, dpr: 1.5 }))).toEqual({ width: 870.6666870117188, height: 968 });
  });

  it("prefers the visual viewport, falls back to the layout viewport, else null", () => {
    expect(cssViewportFromMetrics({ cssVisualViewport: { clientWidth: 800, clientHeight: 600 }, cssLayoutViewport: { clientWidth: 900, clientHeight: 700 } })).toEqual({ width: 800, height: 600 });
    expect(cssViewportFromMetrics({ cssLayoutViewport: { clientWidth: 1024, clientHeight: 768 } })).toEqual({ width: 1024, height: 768 });
    expect(cssViewportFromMetrics({ cssVisualViewport: { clientWidth: 0, clientHeight: 0 }, cssLayoutViewport: { clientWidth: 1024, clientHeight: 768 } })).toEqual({ width: 1024, height: 768 });
    expect(cssViewportFromMetrics({})).toBeNull();
    expect(cssViewportFromMetrics(null)).toBeNull();
  });

  it("takes width and height too, if a browser sends those", () => {
    expect(cssViewportFromMetrics({ cssVisualViewport: { width: 800, height: 600 } })).toEqual({ width: 800, height: 600 });
  });
});
