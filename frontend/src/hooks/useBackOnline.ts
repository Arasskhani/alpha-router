import { useEffect, useRef } from "react";

/**
 * Call `onBack` when the device is back: the connection returns, or the app
 * comes into view again while online (iOS pauses a web app in the background).
 */
export function useBackOnline(onBack: () => void): void {
  const latest = useRef(onBack);
  useEffect(() => {
    latest.current = onBack;
  });
  useEffect(() => {
    const run = () => {
      if (document.visibilityState === "visible" && navigator.onLine !== false) latest.current();
    };
    window.addEventListener("online", run);
    document.addEventListener("visibilitychange", run);
    return () => {
      window.removeEventListener("online", run);
      document.removeEventListener("visibilitychange", run);
    };
  }, []);
}
