import { useEffect, useState } from "react";
import {
  fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl,
} from "../lib/mediaUrl";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";

type Props = {
  url: string;
  alt: string;
  className?: string;
};

export default function AuthenticatedImage({ url, alt, className }: Props) {
  const [src, setSrc] = useState<string | null>(() =>
    url && !isAlphaRouterMediaFileUrl(url) ? safeBrowserUrl(url, "image") : null,
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!url) {
      setSrc(null);
      setFailed(false);
      return;
    }
    if (!isAlphaRouterMediaFileUrl(url)) {
      const safeUrl = safeBrowserUrl(url, "image");
      setSrc(safeUrl);
      setFailed(!safeUrl);
      return;
    }

    let objectUrl: string | null = null;
    let cancelled = false;
    setSrc(null);
    setFailed(false);

    void (async () => {
      try {
        objectUrl = await fetchAuthenticatedMediaObjectUrl(url);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setSrc(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  if (failed) {
    return <div className="alpha-router-generated-image alpha-router-generated-image--error">Image unavailable</div>;
  }
  if (!src) {
    return <div className="alpha-router-generated-image alpha-router-generated-image--loading">Loading image…</div>;
  }
  return <img src={src} alt={alt} className={className} />;
}
