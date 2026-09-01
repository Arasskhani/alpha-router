import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../lib/mediaUrl";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";
export default function AuthenticatedImage({ url, alt, className }) {
    const [src, setSrc] = useState(() => url && !isAlphaRouterMediaFileUrl(url) ? safeBrowserUrl(url, "image") : null);
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
        return _jsx("div", { className: "alpha-router-generated-image alpha-router-generated-image--error", children: "Image unavailable" });
    }
    if (!src) {
        return _jsx("div", { className: "alpha-router-generated-image alpha-router-generated-image--loading", children: "Loading image\u2026" });
    }
    return _jsx("img", { src: src, alt: alt, className: className });
}
