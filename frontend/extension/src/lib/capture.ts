/**
 * Screenshots for the agent: the viewport, or a region to zoom into.
 *
 * A capture goes through CDP `Page.captureScreenshot` with a clip in CSS
 * pixels. Chrome answers in device pixels - the clip times its scale times the
 * display scale - so the clip's scale is the frame scale (coords.ts) divided by
 * the display scale, and the image comes back at frame size: the longest side
 * bounded by maxSide, whatever the screen, as JPEG to keep it small. The CSS
 * viewport size and the display scale come from `Page.getLayoutMetrics`, so the
 * returned frame is the one that maps the model's coordinates back to CSS
 * pixels; and the image's real size is read back, so a frame that does not
 * match it is corrected rather than trusted.
 *
 * `captureVisibleFallback` is the dom driver's path (and CDP's safety net):
 * `chrome.tabs.captureVisibleTab` grabs the active tab only, with no scale
 * control, so the caller keeps the frame from the viewport size separately.
 */

import type { CdpSession } from "./cdp";
import { cssViewportFromMetrics, deviceScaleFromMetrics, type Frame, frameFor, type Size } from "./coords";

export type Shot = { dataUrl: string; frame: Frame; css: Size };
export type Region = { x: number; y: number; width: number; height: number };

/** A last-resort viewport size when the page reports none (a blank or detached page). */
const FALLBACK_VIEWPORT: Size = { width: 1280, height: 800 };
const JPEG_QUALITY = 70;

/** The viewport as a capture needs it: its CSS size, and device pixels per CSS pixel. */
type Viewport = { css: Size; dpr: number };

async function viewport(session: CdpSession): Promise<Viewport> {
  const metrics = await session.send("Page.getLayoutMetrics");
  return { css: cssViewportFromMetrics(metrics) ?? FALLBACK_VIEWPORT, dpr: deviceScaleFromMetrics(metrics) };
}

export async function viewportSize(session: CdpSession): Promise<Size> {
  return (await viewport(session)).css;
}

function dataUrl(result: unknown): string {
  const data = (result as { data?: string })?.data;
  if (!data) throw new Error("captureScreenshot returned no image");
  return `data:image/jpeg;base64,${data}`;
}

/** A JPEG's size, from its frame header near the start; null when the data is not a JPEG we can read. */
export function jpegSize(url: string): Size | null {
  const data = url.slice(url.indexOf(",") + 1);
  let bytes: Uint8Array;
  try {
    // The frame header sits in the first few hundred bytes, after the tables; 8192 is a whole number of base64 quads.
    const head = atob(data.length <= 8192 ? data : data.slice(0, 8192));
    bytes = Uint8Array.from(head, (c) => c.charCodeAt(0));
  } catch {
    return null;
  }
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  let i = 2;
  while (i + 9 < bytes.length) {
    if (bytes[i] !== 0xff) return null;
    const marker = bytes[i + 1];
    const length = (bytes[i + 2] << 8) | bytes[i + 3];
    // SOF0-SOF15, less DHT (C4), JPG (C8) and DAC (CC): the frame header, with the height, then the width.
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { width: (bytes[i + 7] << 8) | bytes[i + 8], height: (bytes[i + 5] << 8) | bytes[i + 6] };
    }
    i += 2 + length;
  }
  return null;
}

/**
 * The frame an image really is. Expected to be `frame`; when the image is
 * another size (a display scale the metrics did not show), the frame is taken
 * from the image, so the model's coordinates still map back to the right CSS
 * pixel.
 */
function frameOf(url: string, frame: Frame, css: Size): Frame {
  const size = jpegSize(url);
  if (!size || (Math.abs(size.width - frame.width) <= 2 && Math.abs(size.height - frame.height) <= 2)) return frame;
  return { width: size.width, height: size.height, scale: size.width / css.width };
}

/** The whole viewport, scaled to the frame the model reads and answers in. */
export async function captureViewport(session: CdpSession, maxSide: number): Promise<Shot> {
  const { css, dpr } = await viewport(session);
  const frame = frameFor(css, maxSide);
  const result = await session.send("Page.captureScreenshot", {
    format: "jpeg",
    quality: JPEG_QUALITY,
    clip: { x: 0, y: 0, width: css.width, height: css.height, scale: frame.scale / dpr },
    captureBeyondViewport: false,
  });
  const url = dataUrl(result);
  return { dataUrl: url, frame: frameOf(url, frame, css), css };
}

/** A region magnified: its own pixels scaled up to fill the frame, for a closer look. */
export async function captureRegion(session: CdpSession, region: Region, maxSide: number): Promise<Shot> {
  const { dpr } = await viewport(session);
  const size: Size = { width: Math.max(1, region.width), height: Math.max(1, region.height) };
  // Zoom magnifies: unlike the viewport, a small region is scaled UP to fill maxSide.
  const scale = maxSide / Math.max(size.width, size.height);
  const frame: Frame = { width: Math.round(size.width * scale), height: Math.round(size.height * scale), scale };
  const result = await session.send("Page.captureScreenshot", {
    format: "jpeg",
    quality: JPEG_QUALITY,
    clip: { x: region.x, y: region.y, width: size.width, height: size.height, scale: frame.scale / dpr },
    captureBeyondViewport: false,
  });
  const url = dataUrl(result);
  return { dataUrl: url, frame: frameOf(url, frame, size), css: size };
}

/** The active tab's visible area, for the dom driver or when a CDP capture fails. */
export async function captureVisibleFallback(windowId: number): Promise<string> {
  return await chrome.tabs.captureVisibleTab(windowId, { format: "jpeg", quality: JPEG_QUALITY });
}
