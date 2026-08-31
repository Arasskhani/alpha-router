import { describe, expect, it } from "vitest";
import {
  containFit,
  isCropLargeEnough,
  mapDisplayedRectToImage,
  MIN_CROP_PX,
  normalizeDragRect,
  screenshotFileName,
  screenshotPermissionErrorMessage,
} from "./screenshotCapture";

describe("normalizeDragRect", () => {
  it("orders any drag direction into a positive rectangle", () => {
    expect(normalizeDragRect({ x: 80, y: 60 }, { x: 20, y: 10 })).toEqual({
      x: 20,
      y: 10,
      width: 60,
      height: 50,
    });
  });
});

describe("containFit + mapDisplayedRectToImage", () => {
  it("maps a selection on a letterboxed image back to pixel coordinates", () => {
    const fit = containFit(200, 100, 400, 400);
    expect(fit.drawWidth).toBe(400);
    expect(fit.drawHeight).toBe(200);
    expect(fit.offsetX).toBe(0);
    expect(fit.offsetY).toBe(100);

    const mapped = mapDisplayedRectToImage(
      { x: 40, y: 120, width: 80, height: 40 },
      fit,
      200,
      100,
    );
    expect(mapped).toEqual({ x: 20, y: 10, width: 40, height: 20 });
  });

  it("clamps a selection that starts outside the image", () => {
    const fit = containFit(100, 100, 100, 100);
    const mapped = mapDisplayedRectToImage(
      { x: -10, y: -5, width: 30, height: 20 },
      fit,
      100,
      100,
    );
    expect(mapped).toEqual({ x: 0, y: 0, width: 20, height: 15 });
  });

  it("returns null for an empty mapped crop", () => {
    const fit = containFit(100, 100, 100, 100);
    expect(mapDisplayedRectToImage({ x: 200, y: 200, width: 10, height: 10 }, fit, 100, 100)).toBe(
      null,
    );
  });
});

describe("isCropLargeEnough", () => {
  it("rejects tiny selections", () => {
    expect(isCropLargeEnough({ x: 0, y: 0, width: MIN_CROP_PX - 1, height: 80 })).toBe(false);
    expect(isCropLargeEnough({ x: 0, y: 0, width: MIN_CROP_PX, height: MIN_CROP_PX })).toBe(true);
  });
});

describe("screenshotFileName", () => {
  it("uses a stable screenshot-YYYYMMDD-HHMMSS.png shape", () => {
    expect(screenshotFileName(new Date(2026, 7, 31, 21, 14, 5))).toBe(
      "screenshot-20260831-211405.png",
    );
  });
});

describe("screenshotPermissionErrorMessage", () => {
  it("maps permission and abort errors to the fallback copy", () => {
    expect(screenshotPermissionErrorMessage({ name: "NotAllowedError" })).toMatch(/cancelled or blocked/);
    expect(screenshotPermissionErrorMessage({ name: "AbortError" })).toMatch(/cancelled or blocked/);
    expect(screenshotPermissionErrorMessage({ name: "NotFoundError" })).toMatch(/not available/);
    expect(screenshotPermissionErrorMessage(new Error("boom"))).toBeNull();
  });
});
