import { useEffect } from "react";

/** The CSS variable the phone layout sizes itself with; its :root default is 100dvh. */
export const VIEWPORT_HEIGHT_VAR = "--app-viewport-height";

/**
 * Keep `--app-viewport-height` equal to the visual viewport's height while
 * `active`.
 *
 * On iOS Safari the on-screen keyboard shrinks the visual viewport but not
 * `100dvh`, so a layout sized with `dvh` keeps its full height and the
 * composer at its bottom ends up behind the keyboard. Chrome on Android
 * resizes the layout itself (`interactive-widget=resizes-content`), and
 * there the two agree anyway. iOS also scrolls the page to bring the focused
 * field into view; once the layout fits the visual viewport there is nothing
 * to scroll, so the page is put back at the top.
 *
 * Pinch-zoom shrinks the visual viewport too, but that is the user looking
 * closer, not less room: while zoomed the height is left as it was and the
 * page is not scrolled, or the layout would halve and the pan jump back.
 */
export function useVisualViewportHeight(active: boolean): void {
  useEffect(() => {
    const viewport = typeof window === "undefined" ? undefined : window.visualViewport;
    if (!active || !viewport) return undefined;
    const root = document.documentElement;
    const apply = () => {
      if (Math.abs(viewport.scale - 1) > 0.01) return;
      root.style.setProperty(VIEWPORT_HEIGHT_VAR, `${Math.round(viewport.height)}px`);
      if (window.scrollY !== 0) window.scrollTo(0, 0);
    };
    apply();
    viewport.addEventListener("resize", apply);
    return () => {
      viewport.removeEventListener("resize", apply);
      root.style.removeProperty(VIEWPORT_HEIGHT_VAR);
    };
  }, [active]);
}
