import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../lib/mediaUrl";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";
export default function AuthenticatedVideo({ url, className, title, controls = true }) {
    const [src, setSrc] = useState(() => url && !isAlphaRouterMediaFileUrl(url) ? safeBrowserUrl(url, "media") : null);
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
        let objectUrl = null;
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
            }
            catch {
                if (!cancelled)
                    setFailed(true);
            }
        })();
        return () => {
            cancelled = true;
            if (objectUrl)
                URL.revokeObjectURL(objectUrl);
        };
    }, [url]);
    if (failed) {
        return _jsx("div", { className: "alpha-router-generated-video alpha-router-generated-video--error", children: "Video unavailable" });
    }
    if (!src) {
        return _jsx("div", { className: "alpha-router-generated-video alpha-router-generated-video--loading", children: "Loading video\u2026" });
    }
    return (_jsx("video", { src: src, className: className, title: title || "Generated video", controls: controls, playsInline: true, preload: "metadata" }));
}
