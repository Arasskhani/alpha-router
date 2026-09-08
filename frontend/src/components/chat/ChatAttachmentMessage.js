import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import AuthenticatedAudio from "../AuthenticatedAudio";
import AuthenticatedImage from "../AuthenticatedImage";
import AuthenticatedVideo from "../AuthenticatedVideo";
import { attachmentDisplayText, } from "../../lib/chatAttachments";
export default function ChatAttachmentMessage({ payload, onOpenImage }) {
    const images = payload.attachments.filter((a) => a.kind === "image");
    const videos = payload.attachments.filter((a) => a.kind === "video");
    const audios = payload.attachments.filter((a) => a.kind === "audio");
    const documents = payload.attachments.filter((a) => a.kind === "document");
    return (_jsxs("div", { className: "alpha-router-attach-msg", children: [payload.userText.trim() ? _jsx("p", { className: "alpha-router-attach-msg__text", children: payload.userText.trim() }) : null, images.length > 0 ? (_jsx("div", { className: "alpha-router-attach-msg__images", children: images.map((img) => {
                    const url = (img.url || img.data_url || "").trim();
                    return (_jsxs("figure", { className: "alpha-router-attach-msg__image", children: [onOpenImage && url ? (_jsx("button", { type: "button", className: "alpha-router-media-open", onClick: () => onOpenImage(url), "aria-label": `Open ${img.name || "image"}`, children: _jsx(AuthenticatedImage, { url: url, alt: img.name, className: "alpha-router-attach-msg__thumb" }) })) : (_jsx(AuthenticatedImage, { url: url, alt: img.name, className: "alpha-router-attach-msg__thumb" })), _jsx("figcaption", { children: img.name })] }, url || img.name));
                }) })) : null, videos.length > 0 ? (_jsx("div", { className: "alpha-router-attach-msg__videos", children: videos.map((clip) => {
                    const url = (clip.url || clip.data_url || "").trim();
                    return (_jsxs("figure", { className: "alpha-router-attach-msg__video", children: [url ? _jsx(AuthenticatedVideo, { url: url, title: clip.name, className: "alpha-router-generated-video alpha-router-attach-msg__video-el" }) : null, _jsx("figcaption", { children: clip.name })] }, url || clip.name));
                }) })) : null, audios.length > 0 ? (_jsx("ul", { className: "alpha-router-attach-msg__audios", children: audios.map((track) => {
                    const url = (track.url || track.data_url || "").trim();
                    return (_jsxs("li", { children: [url ? _jsx(AuthenticatedAudio, { url: url, title: track.name }) : null, _jsx("span", { className: "alpha-router-attach-msg__doc-name", children: track.name })] }, url || track.name));
                }) })) : null, documents.length > 0 ? (_jsx("ul", { className: "alpha-router-attach-msg__docs", children: documents.map((doc) => (_jsxs("li", { children: [_jsx("span", { className: "alpha-router-attach-msg__doc-icon", "aria-hidden": true, children: "\uD83D\uDCC4" }), _jsx("span", { className: "alpha-router-attach-msg__doc-name", children: doc.name })] }, doc.url || doc.name))) })) : null, !payload.userText.trim() && !images.length && !videos.length && !audios.length && !documents.length ? (_jsx("p", { children: attachmentDisplayText(payload) })) : null] }));
}
