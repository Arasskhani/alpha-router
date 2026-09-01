import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../lib/mediaUrl";
import { safeBrowserUrl } from "../lib/browserUrlPolicy";
function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0)
        return "0:00";
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
}
export default function AuthenticatedAudio({ url, className, title, meta }) {
    const [src, setSrc] = useState(() => url && !isAlphaRouterMediaFileUrl(url) ? safeBrowserUrl(url, "media") : null);
    const [failed, setFailed] = useState(false);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(meta?.durationSeconds ?? 0);
    const audioRef = useRef(null);
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
    const togglePlay = () => {
        const audio = audioRef.current;
        if (!audio)
            return;
        if (audio.paused) {
            void audio.play();
        }
        else {
            audio.pause();
        }
    };
    const onSeek = (e) => {
        const audio = audioRef.current;
        if (!audio)
            return;
        const value = Number(e.target.value);
        audio.currentTime = value;
        setCurrentTime(value);
    };
    if (failed) {
        return (_jsx("div", { className: "alpha-router-generated-audio alpha-router-generated-audio--error", children: "Audio unavailable" }));
    }
    return (_jsxs("div", { className: `alpha-router-generated-audio${className ? ` ${className}` : ""}`, children: [_jsx("audio", { ref: audioRef, src: src ?? undefined, title: title || "Generated speech", preload: "metadata", onPlay: () => setPlaying(true), onPause: () => setPlaying(false), onEnded: () => {
                    setPlaying(false);
                    setCurrentTime(0);
                }, onTimeUpdate: (e) => setCurrentTime(e.currentTarget.currentTime), onLoadedMetadata: (e) => {
                    const d = e.currentTarget.duration;
                    if (Number.isFinite(d) && d > 0)
                        setDuration(d);
                } }), _jsx("button", { type: "button", className: "alpha-router-audio-play-btn", onClick: togglePlay, disabled: !src, "aria-label": playing ? "Pause audio" : "Play audio", title: playing ? "Pause" : "Play", children: playing ? (_jsxs("svg", { viewBox: "0 0 24 24", width: "20", height: "20", fill: "currentColor", "aria-hidden": true, children: [_jsx("rect", { x: "6", y: "5", width: "4", height: "14", rx: "1" }), _jsx("rect", { x: "14", y: "5", width: "4", height: "14", rx: "1" })] })) : (_jsx("svg", { viewBox: "0 0 24 24", width: "20", height: "20", fill: "currentColor", "aria-hidden": true, children: _jsx("path", { d: "M8 5v14l11-7z" }) })) }), _jsxs("div", { className: "alpha-router-audio-body", children: [_jsxs("div", { className: "alpha-router-audio-meta", children: [_jsx("span", { className: "alpha-router-audio-meta__title", title: title, children: title || "Generated speech" }), meta?.voice ? (_jsx("span", { className: "alpha-router-audio-meta__voice", children: meta.voice })) : null] }), _jsxs("div", { className: "alpha-router-audio-progress", children: [_jsx("input", { type: "range", min: 0, max: duration || 0, step: 0.01, value: Math.min(currentTime, duration || 0), onChange: onSeek, disabled: !src, "aria-label": "Seek", className: "alpha-router-audio-seek" }), _jsxs("span", { className: "alpha-router-audio-time", children: [formatDuration(currentTime), " / ", formatDuration(duration)] })] })] })] }));
}
