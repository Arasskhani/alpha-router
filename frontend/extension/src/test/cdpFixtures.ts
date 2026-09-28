/**
 * CDP replies in the shape Chromium really sends them, for the unit tests.
 *
 * Recorded from Chromium 141 (`Page.getLayoutMetrics` at display scales 1,
 * 1.25 and 1.5, scrolled and not): the CSS viewports report their size as
 * `clientWidth`/`clientHeight` - never `width`/`height`, which only
 * `cssContentSize` has - and the deprecated viewports without the `css`
 * prefix are in device pixels. A fake in any other shape lets a bug through:
 * the extension once read `width` and ran every capture at a made-up size.
 */

export type MetricsOptions = {
  /** The CSS viewport, as the page's own scripts would see it (clientWidth/clientHeight). */
  width: number;
  height: number;
  /** Device pixels per CSS pixel: the display scale times the page zoom. */
  dpr?: number;
  /** Where the viewport is scrolled to in the document, in CSS pixels. */
  pageX?: number;
  pageY?: number;
  /** The document's size, in CSS pixels. */
  contentWidth?: number;
  contentHeight?: number;
};

/** A `Page.getLayoutMetrics` reply for a viewport of this size, scale and scroll position. */
export function layoutMetrics(options: MetricsOptions) {
  const { width, height, dpr = 1, pageX = 0, pageY = 0 } = options;
  const contentWidth = options.contentWidth ?? width;
  const contentHeight = options.contentHeight ?? height;
  const device = (value: number) => Math.round(value * dpr);
  return {
    layoutViewport: { pageX: device(pageX), pageY: device(pageY), clientWidth: device(width), clientHeight: device(height) },
    visualViewport: { offsetX: 0, offsetY: 0, pageX, pageY, clientWidth: device(width), clientHeight: device(height), scale: 1, zoom: 1 },
    contentSize: { x: 0, y: 0, width: device(contentWidth), height: device(contentHeight) },
    cssLayoutViewport: { pageX, pageY, clientWidth: Math.floor(width), clientHeight: Math.floor(height) },
    cssVisualViewport: { offsetX: 0, offsetY: 0, pageX, pageY, clientWidth: width, clientHeight: height, scale: 1, zoom: 1 },
    cssContentSize: { x: 0, y: 0, width: contentWidth, height: contentHeight },
  };
}
