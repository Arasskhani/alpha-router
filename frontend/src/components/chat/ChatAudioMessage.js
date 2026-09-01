import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../../lib/mediaUrl";
import { safeBrowserUrl } from "../../lib/browserUrlPolicy";
export default function ChatAudioMessage({ url, transcript }) {
    const [src, setSrc] = useState(null);
    const [error, setError] = useState("");
    useEffect(() => {
        let objectUrl = null;
        let cancelled = false;
        async function load() {
            try {
                if (isAlphaRouterMediaFileUrl(url)) {
                    objectUrl = await fetchAuthenticatedMediaObjectUrl(url);
                    if (!cancelled)
                        setSrc(objectUrl);
                    return;
                }
                const safeUrl = safeBrowserUrl(url, "media");
                if (!safeUrl)
                    throw new Error("Blocked unsafe audio URL.");
                if (!cancelled)
                    setSrc(safeUrl);
            }
            catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : String(err));
                }
            }
        }
        void load();
        return () => {
            cancelled = true;
            if (objectUrl)
                URL.revokeObjectURL(objectUrl);
        };
    }, [url]);
    return (_jsxs("div", { className: "alpha-router-audio-msg", children: [error ? _jsx("p", { className: "alpha-router-audio-msg__error", children: error }) : null, src ? (_jsx("audio", { className: "alpha-router-audio-msg__player", controls: true, preload: "metadata", src: src, children: _jsx("track", { kind: "captions" }) })) : !error ? (_jsx("span", { className: "alpha-router-audio-msg__loading", children: "Loading audio\u2026" })) : null, transcript ? _jsx("p", { className: "alpha-router-audio-msg__transcript", children: transcript }) : null] }));
}
