import { useEffect, useState } from "react";
import type { BrowserUrlKind } from "../lib/browserUrlPolicy";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";
import { fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl } from "../lib/mediaUrl";

type Fetched = { url: string; src: string | null; failed: boolean };

/**
 * Resolve a media URL to something an <img>/<audio>/<video> can load.
 *
 * A plain URL is checked against the browser URL policy and used as is. An
 * Alpharouter media-file URL needs the session cookie, so it is fetched and
 * turned into an object URL, revoked when the URL changes or the component
 * unmounts.
 *
 * Three components carried this logic each in its own effect, and each reset
 * its state with setState calls at the top of the effect - the pattern
 * react-hooks/set-state-in-effect flags, because it forces a second render
 * for what is really a derived value. Here the synchronous cases are derived
 * during render, and the only state is the result of the fetch, tagged with
 * the URL it belongs to so a stale result for an earlier URL is ignored
 * rather than reset.
 */
export function useAuthenticatedMediaSource(url: string, kind: BrowserUrlKind): { src: string | null; failed: boolean } {
  const needsFetch = !!url && isAlphaRouterMediaFileUrl(url);
  const direct = url && !needsFetch ? safeBrowserUrl(url, kind) : null;
  const [fetched, setFetched] = useState<Fetched | null>(null);

  useEffect(() => {
    if (!needsFetch) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    void (async () => {
      try {
        objectUrl = await fetchAuthenticatedMediaObjectUrl(url);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setFetched({ url, src: objectUrl, failed: false });
      } catch {
        if (!cancelled) setFetched({ url, src: null, failed: true });
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, needsFetch]);

  if (!url) return { src: null, failed: false };
  if (!needsFetch) return { src: direct, failed: !direct };
  const current = fetched && fetched.url === url ? fetched : null;
  return { src: current?.src ?? null, failed: current?.failed ?? false };
}
