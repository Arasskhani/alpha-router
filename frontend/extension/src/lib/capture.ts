/**
 * Screenshots for the agent: the viewport, or a region to zoom into.
 *
 * A capture goes through CDP `Page.captureScreenshot` with a clip whose scale is
 * the frame scale (coords.ts), so the image comes back already at frame size -
 * the longest side bounded by maxSide - as JPEG to keep it small. The CSS
 * viewport size comes from `Page.getLayoutMetrics`, so the returned frame is the
 * one that maps the model's coordinates back to CSS pixels.
 *
 * `captureVisibleFallback` is the dom driver's path (and CDP's safety net):
 * `chrome.tabs.captureVisibleTab` grabs the active tab only, with no scale
 * control, so the caller keeps the frame from the viewport size separately.
 */

import type { CdpSession } from "./cdp";
import { cssViewportFromMetrics, type Frame, frameFor, type Size } from "./coords";

export type Shot = { dataUrl: string; frame: Frame; css: Size };
export type Region = { x: number; y: number; width: number; height: number };

/** A last-resort viewport size when the page reports none (a blank or detached page). */
const FALLBACK_VIEWPORT: Size = { width: 1280, height: 800 };
const JPEG_QUALITY = 70;

export async function viewportSize(session: CdpSession): Promise<Size> {
  const metrics = await session.send("Page.getLayoutMetrics");
  return cssViewportFromMetrics(metrics) ?? FALLBACK_VIEWPORT;
}

function dataUrl(result: unknown): string {
  const data = (result as { data?: string })?.data;
  if (!data) throw new Error("captureScreenshot returned no image");
  return `data:image/jpeg;base64,${data}`;
}

/** The whole viewport, scaled to the frame the model reads and answers in. */
export async function captureViewport(session: CdpSession, maxSide: number): Promise<Shot> {
  const css = await viewportSize(session);
  const frame = frameFor(css, maxSide);
  const result = await session.send("Page.captureScreenshot", {
    format: "jpeg",
    quality: JPEG_QUALITY,
    clip: { x: 0, y: 0, width: css.width, height: css.height, scale: frame.scale },
    captureBeyondViewport: false,
  });
  return { dataUrl: dataUrl(result), frame, css };
}

/** A region magnified: its own pixels scaled up to fill the frame, for a closer look. */
export async function captureRegion(session: CdpSession, region: Region, maxSide: number): Promise<Shot> {
  const size: Size = { width: Math.max(1, region.width), height: Math.max(1, region.height) };
  // Zoom magnifies: unlike the viewport, a small region is scaled UP to fill maxSide.
  const scale = maxSide / Math.max(size.width, size.height);
  const frame: Frame = { width: Math.round(size.width * scale), height: Math.round(size.height * scale), scale };
  const result = await session.send("Page.captureScreenshot", {
    format: "jpeg",
    quality: JPEG_QUALITY,
    clip: { x: region.x, y: region.y, width: size.width, height: size.height, scale: frame.scale },
    captureBeyondViewport: false,
  });
  return { dataUrl: dataUrl(result), frame, css: size };
}

/** The active tab's visible area, for the dom driver or when a CDP capture fails. */
export async function captureVisibleFallback(windowId: number): Promise<string> {
  return await chrome.tabs.captureVisibleTab(windowId, { format: "jpeg", quality: JPEG_QUALITY });
}
