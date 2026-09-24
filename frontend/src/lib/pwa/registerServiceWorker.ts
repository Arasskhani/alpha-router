import { getCachedSession } from "../../api";

let started = false;

/**
 * Whether this page may register the app's service worker (public/sw.js).
 *
 * The server's switch must be explicitly on: a missing session or an older
 * payload must never register a worker the server is retiring, or it would
 * install and unregister on every load. navigator.webdriver skips the server's
 * own headless PDF renderer, which loads the app at http://127.0.0.1 (a secure
 * context), and other automated browsers.
 */
function allowed(): boolean {
  if (!import.meta.env.PROD) return false;
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return false;
  if (navigator.webdriver === true) return false;
  const features = getCachedSession()?.features as Record<string, unknown> | null | undefined;
  return features?.pwa_service_worker === true;
}

/**
 * Register the service worker once per page, after the session is known.
 * The session often arrives after the load event, so it registers at once when
 * the page has already loaded. Failures are logged, never shown.
 */
export function registerAppServiceWorker(): void {
  if (started || !allowed()) return;
  started = true;
  const register = () => {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch((err: unknown) => console.warn("Alpharouter: the service worker could not be registered", err));
  };
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register, { once: true });
}
