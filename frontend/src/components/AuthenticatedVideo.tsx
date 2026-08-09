import { useEffect, useState } from "react";
import {
  fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl,
} from "../lib/mediaUrl";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";

type Props = {
  url: string;
  className?: string;
  title?: string;
};

export default function AuthenticatedVideo({ url, className, title }: Props) {
  const [src, setSrc] = useState<string | null>(() =>
    url && !isAlphaRouterMediaFileUrl(url) ? safeBrowserUrl(url, "media") : null,
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!url) {
      setSrc(null);
      setFailed(false);
      return;
    }
    if (!isAlphaRouterMediaFileUrl(url)) {
      const safeUrl = safeBrowserUrl(url, "media");
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
    return <div className="alpha-router-generated-video alpha-router-generated-video--error">Video unavailable</div>;
  }
  if (!src) {
    return <div className="alpha-router-generated-video alpha-router-generated-video--loading">Loading video…</div>;
  }
  return (
    <video
      src={src}
      className={className}
      title={title || "Generated video"}
      controls
      playsInline
      preload="metadata"
    />
  );
}
