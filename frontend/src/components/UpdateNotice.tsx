import { useUpdateAvailable } from "../lib/pwa/appUpdate";

/**
 * "A new version of Alpharouter is available." with Reload, in the layout's
 * flow above the tab bar. It takes the install suggestion's place; the two
 * never show together. It never reloads by itself.
 */
export default function UpdateNotice() {
  const available = useUpdateAvailable();
  if (!available) return null;
  return (
    <div className="app-notice" role="status">
      <span className="app-notice__text">A new version of Alpharouter is available.</span>
      <button type="button" className="app-notice__action" onClick={() => window.location.reload()}>
        Reload
      </button>
    </div>
  );
}
