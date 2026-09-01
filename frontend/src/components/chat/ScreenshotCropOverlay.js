import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { containFit, cropScreenshotToFile, isCropLargeEnough, mapDisplayedRectToImage, MIN_CROP_PX, normalizeDragRect, } from "../../lib/screenshotCapture";
export default function ScreenshotCropOverlay({ frame, onCancel, onConfirm }) {
    const stageRef = useRef(null);
    const imgRef = useRef(null);
    const dragOrigin = useRef(null);
    const [draft, setDraft] = useState(null);
    const [selection, setSelection] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    useEffect(() => {
        setDraft(null);
        setSelection(null);
        setBusy(false);
        setError("");
    }, [frame?.objectUrl]);
    useEffect(() => {
        if (!frame)
            return;
        const onKey = (e) => {
            if (e.key === "Escape") {
                e.preventDefault();
                if (!busy)
                    onCancel();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [frame, busy, onCancel]);
    if (!frame)
        return null;
    function pointInStage(clientX, clientY) {
        const stage = stageRef.current;
        if (!stage)
            return null;
        const box = stage.getBoundingClientRect();
        return { x: clientX - box.left, y: clientY - box.top };
    }
    function readFit() {
        const stage = stageRef.current;
        const img = imgRef.current;
        if (!stage || !img || !frame) {
            return containFit(frame?.width || 0, frame?.height || 0, 1, 1);
        }
        const stageBox = stage.getBoundingClientRect();
        const imgBox = img.getBoundingClientRect();
        if (imgBox.width > 0 && imgBox.height > 0) {
            return {
                offsetX: imgBox.left - stageBox.left,
                offsetY: imgBox.top - stageBox.top,
                drawWidth: imgBox.width,
                drawHeight: imgBox.height,
            };
        }
        return containFit(frame.width, frame.height, stageBox.width, stageBox.height);
    }
    function onPointerDown(e) {
        if (busy)
            return;
        const pt = pointInStage(e.clientX, e.clientY);
        if (!pt)
            return;
        dragOrigin.current = pt;
        setDraft({ x: pt.x, y: pt.y, width: 0, height: 0 });
        e.currentTarget.setPointerCapture(e.pointerId);
    }
    function onPointerMove(e) {
        const origin = dragOrigin.current;
        if (!origin)
            return;
        const pt = pointInStage(e.clientX, e.clientY);
        if (!pt)
            return;
        setDraft(normalizeDragRect(origin, pt));
    }
    function onPointerUp(e) {
        const origin = dragOrigin.current;
        dragOrigin.current = null;
        const pt = pointInStage(e.clientX, e.clientY);
        setDraft(null);
        if (!origin || !pt)
            return;
        const rect = normalizeDragRect(origin, pt);
        if (!isCropLargeEnough(rect))
            return;
        setSelection(rect);
    }
    const visible = draft || selection;
    const canUse = !!selection && isCropLargeEnough(selection);
    async function confirm() {
        if (!frame || !selection || busy)
            return;
        const imageRect = mapDisplayedRectToImage(selection, readFit(), frame.width, frame.height);
        if (!imageRect || !isCropLargeEnough(imageRect, MIN_CROP_PX)) {
            setError("Drag a larger area to attach.");
            return;
        }
        setBusy(true);
        setError("");
        try {
            const file = await cropScreenshotToFile(frame, imageRect);
            await onConfirm(file);
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setBusy(false);
        }
    }
    return (_jsxs("div", { className: "alpha-router-screenshot-crop", role: "dialog", "aria-modal": "true", "aria-label": "Crop screenshot", children: [_jsxs("div", { className: "alpha-router-screenshot-crop__bar", children: [_jsx("p", { children: "Drag to select the area to attach. Esc cancels." }), error ? _jsx("p", { className: "alpha-router-screenshot-crop__error", children: error }) : null, _jsxs("div", { className: "alpha-router-screenshot-crop__actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onCancel, disabled: busy, children: "Cancel" }), _jsx("button", { type: "button", className: "btn", onClick: () => void confirm(), disabled: !canUse || busy, children: busy ? "Attaching…" : "Use selection" })] })] }), _jsxs("div", { ref: stageRef, className: "alpha-router-screenshot-crop__stage", onPointerDown: onPointerDown, onPointerMove: onPointerMove, onPointerUp: onPointerUp, onPointerCancel: onPointerUp, children: [_jsx("img", { ref: imgRef, src: frame.objectUrl, alt: "Captured screen", draggable: false, className: "alpha-router-screenshot-crop__image" }), visible ? (_jsx("div", { className: "alpha-router-screenshot-crop__rect", style: {
                            left: visible.x,
                            top: visible.y,
                            width: visible.width,
                            height: visible.height,
                        } })) : null] })] }));
}
