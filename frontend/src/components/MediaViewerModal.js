import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect } from "react";
import AuthenticatedImage from "./AuthenticatedImage";
import AuthenticatedVideo from "./AuthenticatedVideo";
import Modal from "./Modal";
import { ChevronLeftIcon, ChevronRightIcon, OpenFullSizeIcon } from "./chat/GeneratedImageIcons";
export default function MediaViewerModal({ items, index, onClose, onIndexChange, onOpenExternal, }) {
    const currentIndex = index != null && index >= 0 && index < items.length ? index : null;
    const open = currentIndex != null;
    const current = open ? items[currentIndex] : null;
    const showNav = items.length > 1;
    const canPrev = currentIndex != null && currentIndex > 0;
    const canNext = currentIndex != null && currentIndex < items.length - 1;
    useEffect(() => {
        if (!open)
            return;
        const onKey = (event) => {
            if (event.key === "ArrowLeft" && canPrev) {
                event.preventDefault();
                onIndexChange(currentIndex - 1);
            }
            else if (event.key === "ArrowRight" && canNext) {
                event.preventDefault();
                onIndexChange(currentIndex + 1);
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, currentIndex, canPrev, canNext, onIndexChange]);
    return (_jsx(Modal, { open: open, title: current?.title || current?.alt || "Media", onClose: onClose, compactHeader: true, panelClassName: "modal-panel--media-viewer", bodyClassName: "media-viewer-body", headerActions: current && onOpenExternal ? (_jsx("button", { type: "button", className: "media-viewer__external", title: "Open in new tab", "aria-label": "Open in new tab", onClick: () => onOpenExternal(current), children: _jsx(OpenFullSizeIcon, {}) })) : null, children: current ? (_jsxs("div", { className: "media-viewer", children: [showNav ? (_jsx("button", { type: "button", className: "media-viewer__nav media-viewer__nav--prev", "aria-label": "Previous", disabled: !canPrev, onClick: () => canPrev && currentIndex != null && onIndexChange(currentIndex - 1), children: _jsx(ChevronLeftIcon, {}) })) : (_jsx("span", { className: "media-viewer__nav-spacer media-viewer__nav-spacer--prev", "aria-hidden": true })), _jsx("div", { className: "media-viewer__stage", children: current.kind === "video" ? (_jsx(AuthenticatedVideo, { url: current.url, className: "media-viewer__media", title: current.title || current.alt || "Video" }, current.id)) : (_jsx(AuthenticatedImage, { url: current.url, alt: current.alt || "Image", className: "media-viewer__media" }, current.id)) }), showNav ? (_jsx("button", { type: "button", className: "media-viewer__nav media-viewer__nav--next", "aria-label": "Next", disabled: !canNext, onClick: () => canNext && currentIndex != null && onIndexChange(currentIndex + 1), children: _jsx(ChevronRightIcon, {}) })) : (_jsx("span", { className: "media-viewer__nav-spacer media-viewer__nav-spacer--next", "aria-hidden": true })), _jsxs("p", { className: "media-viewer__meta", children: [showNav ? (_jsxs("span", { children: [currentIndex != null ? currentIndex + 1 : 0, " / ", items.length] })) : null, current.title ? _jsx("span", { className: "media-viewer__caption", children: current.title }) : null] })] })) : null }));
}
