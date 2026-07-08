import { useEffect, useState } from "react";
import {
  fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl,
} from "../../lib/mediaUrl";

type Props = {
  url: string;
  transcript?: string;
};

export default function ChatAudioMessage({ url, transcript }: Props) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    async function load() {
      try {
        if (isAlphaRouterMediaFileUrl(url)) {
          objectUrl = await fetchAuthenticatedMediaObjectUrl(url);
          if (!cancelled) setSrc(objectUrl);
          return;
        }
        if (!cancelled) setSrc(url);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  return (
    <div className="cgpt-audio-msg">
      {error ? <p className="cgpt-audio-msg__error">{error}</p> : null}
      {src ? (
        <audio className="cgpt-audio-msg__player" controls preload="metadata" src={src}>
          <track kind="captions" />
        </audio>
      ) : !error ? (
        <span className="cgpt-audio-msg__loading">Loading audio…</span>
      ) : null}
      {transcript ? <p className="cgpt-audio-msg__transcript">{transcript}</p> : null}
    </div>
  );
}
