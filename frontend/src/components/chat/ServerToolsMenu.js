import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { DEFAULT_CHAT_TOOLS, videoDurationChoices } from "../../lib/chatTools";
import { DEFAULT_CUSTOM_ASPECT_RATIO, IMAGE_ASPECT_PRESETS, normalizeCustomAspectRatio, normalizeImageAspectPreset, SUPPORTED_ASPECT_RATIOS, } from "../../lib/imageSize";
function Toggle({ on, onToggle, label, disabled = false, disabledTitle, }) {
    return (_jsx("button", { type: "button", className: `alpha-router-toggle${on ? " on" : ""}`, disabled: disabled, title: disabled ? disabledTitle : undefined, onClick: (e) => {
            e.stopPropagation();
            onToggle();
        }, "aria-label": label, "aria-pressed": on, children: _jsx("span", { className: "alpha-router-toggle-knob" }) }));
}
function ToolRow({ icon, title, description, on, onToggle, disabled = false, disabledTitle, }) {
    return (_jsxs("div", { className: `alpha-router-server-tool${disabled ? " is-disabled" : ""}`, onMouseDown: (e) => e.stopPropagation(), title: disabled ? disabledTitle : undefined, children: [_jsx("span", { className: "alpha-router-server-tool__icon", "aria-hidden": true, children: icon }), _jsxs("div", { className: "alpha-router-server-tool__text", children: [_jsx("strong", { children: title }), _jsx("span", { className: "alpha-router-server-tool__desc", children: description })] }), _jsx(Toggle, { on: on, onToggle: onToggle, label: `Toggle ${title}`, disabled: disabled, disabledTitle: disabledTitle })] }));
}
const MENU_WIDTH = 300;
export default function ServerToolsMenu({ open, anchorRef, tools, privateMode, onChange, onPrivateModeChange, onClose, allowPrivateMode = true, videoCapabilities, speechCapabilities, }) {
    const [pos, setPos] = useState(null);
    const [customAspectDraft, setCustomAspectDraft] = useState(tools.imageCustomAspectRatio);
    useEffect(() => {
        if (open)
            setCustomAspectDraft(tools.imageCustomAspectRatio);
    }, [open, tools.imageCustomAspectRatio]);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => {
            if (e.key === "Escape")
                onClose();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, onClose]);
    useLayoutEffect(() => {
        if (!open) {
            setPos(null);
            return;
        }
        const place = () => {
            const el = anchorRef.current;
            if (!el)
                return;
            const rect = el.getBoundingClientRect();
            const width = Math.min(MENU_WIDTH, window.innerWidth - 16);
            const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
            const bottom = window.innerHeight - rect.top + 8;
            setPos({ left, bottom });
        };
        place();
        window.addEventListener("resize", place);
        window.addEventListener("scroll", place, true);
        return () => {
            window.removeEventListener("resize", place);
            window.removeEventListener("scroll", place, true);
        };
    }, [open, anchorRef]);
    if (!open || !pos)
        return null;
    function patch(partial) {
        onChange({ ...tools, ...partial });
    }
    const activePreset = normalizeImageAspectPreset(tools.imageAspectRatio);
    const customAspectValid = normalizeCustomAspectRatio(customAspectDraft);
    function commitCustomAspect(raw = customAspectDraft) {
        const normalized = normalizeCustomAspectRatio(raw);
        if (normalized) {
            patch({ imageAspectRatio: "custom", imageCustomAspectRatio: normalized });
            setCustomAspectDraft(normalized);
        }
        else if (raw.trim()) {
            setCustomAspectDraft(tools.imageCustomAspectRatio);
        }
    }
    function selectPreset(presetId) {
        patch({ imageAspectRatio: presetId });
    }
    function selectCustom() {
        const normalized = normalizeCustomAspectRatio(customAspectDraft) ?? tools.imageCustomAspectRatio;
        patch({
            imageAspectRatio: "custom",
            imageCustomAspectRatio: normalizeCustomAspectRatio(normalized) ?? DEFAULT_CUSTOM_ASPECT_RATIO,
        });
    }
    return createPortal(_jsxs("div", { className: "alpha-router-server-tools-menu", role: "menu", "aria-label": "Chat Tools", style: { left: pos.left, bottom: pos.bottom, width: Math.min(MENU_WIDTH, window.innerWidth - 16) }, onMouseDown: (e) => e.stopPropagation(), onClick: (e) => e.stopPropagation(), children: [_jsx("header", { className: "alpha-router-server-tools-menu__head", children: "Chat Tools" }), _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("circle", { cx: "12", cy: "12", r: "9" }), _jsx("path", { d: "M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20" })] }), title: "Web Search", description: "Fresh web results", on: tools.webSearch, onToggle: () => patch({ webSearch: !tools.webSearch }) }), _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("path", { d: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" }), _jsx("path", { d: "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" })] }), title: "Web Fetch", description: "Read links in your message", on: tools.webFetch, onToggle: () => patch({ webFetch: !tools.webFetch }) }), _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("rect", { x: "3", y: "5", width: "18", height: "14", rx: "2" }), _jsx("circle", { cx: "8.5", cy: "11", r: "1.5" }), _jsx("path", { d: "m21 15-5-5L5 21" })] }), title: "Image Generation", description: "Create or edit images from text", on: tools.imageGeneration, onToggle: () => patch({
                    imageGeneration: !tools.imageGeneration,
                    videoGeneration: !tools.imageGeneration ? false : tools.videoGeneration,
                    speechGeneration: !tools.imageGeneration ? false : tools.speechGeneration,
                }) }), tools.imageGeneration ? (_jsxs("div", { className: "alpha-router-image-aspect-picker", onMouseDown: (e) => e.stopPropagation(), children: [_jsx("span", { className: "alpha-router-image-aspect-picker__label", children: "Aspect ratio" }), _jsxs("div", { className: "alpha-router-image-aspect-picker__options", role: "group", "aria-label": "Image aspect ratio", children: [IMAGE_ASPECT_PRESETS.map((preset) => {
                                const active = activePreset === preset.id;
                                return (_jsx("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${active ? " active" : ""}`, "aria-pressed": active, title: `${preset.label} (${preset.aspectRatio})`, onClick: () => selectPreset(preset.id), children: preset.shortLabel }, preset.id));
                            }), _jsx("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${activePreset === "custom" ? " active" : ""}`, "aria-pressed": activePreset === "custom", title: "Custom aspect ratio (W:H)", onClick: selectCustom, children: "Custom" })] }), activePreset === "custom" ? (_jsxs("div", { className: "alpha-router-image-aspect-picker__custom", children: [_jsx("input", { type: "text", className: "alpha-router-image-aspect-picker__custom-input", value: customAspectDraft, placeholder: DEFAULT_CUSTOM_ASPECT_RATIO, "aria-label": "Custom aspect ratio (width:height)", onChange: (e) => {
                                    const v = e.target.value;
                                    setCustomAspectDraft(v);
                                    const normalized = normalizeCustomAspectRatio(v);
                                    if (normalized) {
                                        patch({ imageAspectRatio: "custom", imageCustomAspectRatio: normalized });
                                    }
                                }, onBlur: () => commitCustomAspect(), onKeyDown: (e) => {
                                    if (e.key === "Enter") {
                                        e.preventDefault();
                                        commitCustomAspect();
                                    }
                                } }), _jsx("span", { className: "alpha-router-image-aspect-picker__custom-hint", children: customAspectValid
                                    ? `${customAspectValid} (supported: ${SUPPORTED_ASPECT_RATIOS.join(", ")})`
                                    : `W:H e.g. 21:9 or 16:9` })] })) : null, _jsxs("span", { className: "alpha-router-image-aspect-picker__hint", children: ["Text-to-image uses this aspect ratio. With a source attachment (image-to-image), output size matches the source image. Override in prompt: ", _jsx("code", { children: "--ar 16:9" })] })] })) : null, _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("rect", { x: "3", y: "6", width: "14", height: "12", rx: "2" }), _jsx("path", { d: "m17 10 4-2v8l-4-2z" })] }), title: "Video Generation", description: "Create videos from text or an image", on: tools.videoGeneration, onToggle: () => patch({
                    videoGeneration: !tools.videoGeneration,
                    imageGeneration: !tools.videoGeneration ? false : tools.imageGeneration,
                    speechGeneration: !tools.videoGeneration ? false : tools.speechGeneration,
                }) }), tools.videoGeneration ? (_jsxs("div", { className: "alpha-router-image-aspect-picker", onMouseDown: (e) => e.stopPropagation(), children: [_jsx("span", { className: "alpha-router-image-aspect-picker__label", children: "Duration / resolution" }), _jsx("div", { className: "alpha-router-image-aspect-picker__options", role: "group", "aria-label": "Video duration", children: videoDurationChoices(videoCapabilities?.supported_durations).map((sec) => {
                            const active = tools.videoDuration === sec;
                            return (_jsxs("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${active ? " active" : ""}`, "aria-pressed": active, onClick: () => patch({ videoDuration: sec }), children: [sec, "s"] }, sec));
                        }) }), _jsx("div", { className: "alpha-router-image-aspect-picker__options", role: "group", "aria-label": "Video resolution", children: (videoCapabilities?.supported_resolutions?.length
                            ? videoCapabilities.supported_resolutions
                            : ["480p", "720p", "1080p"]).map((res) => {
                            const active = tools.videoResolution === res;
                            return (_jsx("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${active ? " active" : ""}`, "aria-pressed": active, onClick: () => patch({ videoResolution: res }), children: res }, res));
                        }) }), _jsx("div", { className: "alpha-router-image-aspect-picker__options", role: "group", "aria-label": "Video aspect ratio", children: (videoCapabilities?.supported_aspect_ratios?.length
                            ? videoCapabilities.supported_aspect_ratios
                            : ["16:9", "9:16", "1:1"]).map((ar) => {
                            const active = tools.videoAspectRatio === ar;
                            return (_jsx("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${active ? " active" : ""}`, "aria-pressed": active, onClick: () => patch({ videoAspectRatio: ar }), children: ar }, ar));
                        }) }), _jsx("span", { className: "alpha-router-image-aspect-picker__hint", children: "Text-to-video uses these settings. Attach an image to animate it (image-to-video)." }), _jsxs("label", { className: "alpha-router-image-aspect-picker__audio", children: [_jsx("input", { type: "checkbox", checked: tools.videoGenerateAudio, onChange: (e) => patch({ videoGenerateAudio: e.target.checked }) }), "Generate audio when supported"] })] })) : null, _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("path", { d: "M11 5 6 9H2v6h4l5 4V5z" }), _jsx("path", { d: "M15.54 8.46a5 5 0 0 1 0 7.07" }), _jsx("path", { d: "M19.07 4.93a10 10 0 0 1 0 14.14" })] }), title: "Text to Speech", description: "Generate audio from text", on: tools.speechGeneration, onToggle: () => patch({
                    speechGeneration: !tools.speechGeneration,
                    imageGeneration: !tools.speechGeneration ? false : tools.imageGeneration,
                    videoGeneration: !tools.speechGeneration ? false : tools.videoGeneration,
                }) }), tools.speechGeneration ? (_jsxs("div", { className: "alpha-router-image-aspect-picker", onMouseDown: (e) => e.stopPropagation(), children: [_jsx("span", { className: "alpha-router-image-aspect-picker__label", children: "Voice" }), _jsx("div", { className: "alpha-router-image-aspect-picker__options", role: "group", "aria-label": "Speech voice", children: (speechCapabilities?.supported_voices?.length
                            ? speechCapabilities.supported_voices
                            : []).map((voice) => {
                            const active = tools.speechVoice === voice;
                            return (_jsx("button", { type: "button", className: `alpha-router-image-aspect-picker__chip${active ? " active" : ""}`, "aria-pressed": active, onClick: () => patch({ speechVoice: voice }), children: voice }, voice));
                        }) }), _jsxs("div", { className: "alpha-router-image-aspect-picker__custom", children: [_jsx("span", { className: "alpha-router-image-aspect-picker__label", children: "Speed" }), _jsx("input", { type: "range", min: Number(speechCapabilities?.supported_speeds?.[0] ?? 0.25), max: Number(speechCapabilities?.supported_speeds?.[1] ?? 4.0), step: 0.05, value: tools.speechSpeed, "aria-label": "Speech speed", onChange: (e) => patch({ speechSpeed: Number(e.target.value) }) }), _jsxs("span", { className: "alpha-router-image-aspect-picker__custom-hint", children: [tools.speechSpeed.toFixed(2), "x"] })] }), _jsxs("span", { className: "alpha-router-image-aspect-picker__hint", children: ["Text-to-speech generates audio from your message text. Max", " ", speechCapabilities?.max_text_length ?? 5000, " characters."] })] })) : null, _jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("polyline", { points: "16 18 22 12 16 6" }), _jsx("polyline", { points: "8 6 2 12 8 18" })] }), title: "Code Interpreter", description: "Run Python on data & math", on: tools.codeInterpreter, onToggle: () => patch({ codeInterpreter: !tools.codeInterpreter }) }), allowPrivateMode ? (_jsx(ToolRow, { icon: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("path", { d: "M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5z" }), _jsx("circle", { cx: "12", cy: "14", r: "1.5" })] }), title: "Private Mode", description: privateMode
                    ? "Permanent for this chat — start a new chat for normal mode"
                    : "Store this chat and its media on this device only", on: privateMode, onToggle: () => onPrivateModeChange(!privateMode), disabled: privateMode, disabledTitle: "Private Mode cannot be turned off for this chat. Start a new chat to use normal mode." })) : null, _jsx("footer", { className: "alpha-router-server-tools-menu__foot", children: _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: (e) => {
                        e.stopPropagation();
                        onChange({ ...DEFAULT_CHAT_TOOLS });
                    }, children: "Reset defaults" }) })] }), document.body);
}
