import { useCallback, useMemo, useSyncExternalStore } from "react";

/**
 * Below this width the shell is laid out for a phone: side panels become
 * drawers the topbar menu button opens. styles.css uses the same query for
 * the rules that need no JavaScript; keep the two in step.
 */
export const PHONE_QUERY = "(max-width: 768px)";

/**
 * Below this width the shell's navigation, outside the chat pages, is a
 * drawer behind the topbar's menu button: on phones, and on tablets up to
 * 1024px, where it was a block stacked above the page. styles.css holds the
 * drawer rules in a block with the same query.
 */
export const NAV_DRAWER_QUERY = "(max-width: 1024px)";

function canMatch(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

/** Whether `query` matches now; re-renders when that changes. False where there is no window. */
export function useMediaQuery(query: string): boolean {
  // One list per component and query, so the store subscribes once, not on every render.
  const list = useMemo(() => (canMatch() ? window.matchMedia(query) : null), [query]);
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!list) return () => {};
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [list],
  );
  return useSyncExternalStore(
    subscribe,
    () => list?.matches ?? false,
    () => false,
  );
}

export function usePhoneLayout(): boolean {
  return useMediaQuery(PHONE_QUERY);
}
