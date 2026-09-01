import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { memo, useMemo, useRef, useState } from "react";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import { copyTextToClipboard } from "../../lib/clipboard";
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
/** Lines shown while the block is collapsed (chat + code interpreter). */
export const CODE_BLOCK_COLLAPSED_PREVIEW_LINES = 8;
const MAX_REMEMBERED_EXPAND_STATES = 200;
/** Survives Markdown remounts (scroll / message refresh) so Expand stays open. */
const rememberedExpanded = new Map();
function normalizeLanguage(lang) {
    const raw = (lang || "").trim().toLowerCase();
    if (!raw)
        return "plaintext";
    if (raw === "py")
        return "python";
    if (raw === "text" || raw === "console" || raw === "output")
        return "plaintext";
    return raw;
}
function languageLabel(lang, variant) {
    if (variant === "output")
        return "Output";
    if (lang === "python")
        return "Python";
    if (lang === "plaintext")
        return "Code";
    return lang;
}
function highlightPython(code) {
    if (!code)
        return null;
    try {
        return hljs.highlight(code, { language: "python", ignoreIllegals: true }).value;
    }
    catch {
        return null;
    }
}
/** Visible slice for a collapsed block; full `code` stays available for Copy. */
export function getCollapsedCodePreview(code, maxLines = CODE_BLOCK_COLLAPSED_PREVIEW_LINES) {
    if (!code)
        return { preview: "", truncated: false };
    const lines = code.split("\n");
    if (lines.length <= maxLines) {
        return { preview: code, truncated: false };
    }
    return {
        preview: lines.slice(0, maxLines).join("\n"),
        truncated: true,
    };
}
function hashString(value) {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i++) {
        hash ^= value.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}
/**
 * Stable identity for expand state. Uses the collapsed preview head so streaming
 * the rest of the block does not reset Expand.
 */
export function codeBlockExpandStateKey(code, language, variant) {
    const { preview } = getCollapsedCodePreview(code);
    return `${variant}|${language}|${hashString(preview)}`;
}
function rememberExpanded(key, expanded) {
    if (rememberedExpanded.has(key))
        rememberedExpanded.delete(key);
    rememberedExpanded.set(key, expanded);
    while (rememberedExpanded.size > MAX_REMEMBERED_EXPAND_STATES) {
        const oldest = rememberedExpanded.keys().next().value;
        if (oldest == null)
            break;
        rememberedExpanded.delete(oldest);
    }
}
function findVerticalScrollParent(node) {
    let cur = node?.parentElement ?? null;
    while (cur) {
        const style = window.getComputedStyle(cur);
        const oy = style.overflowY;
        if ((oy === "auto" || oy === "scroll" || oy === "overlay") && cur.scrollHeight > cur.clientHeight) {
            return cur;
        }
        cur = cur.parentElement;
    }
    return null;
}
function ChevronUpIcon() {
    return (_jsx("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2.2", "aria-hidden": true, children: _jsx("path", { d: "M18 15l-6-6-6 6", strokeLinecap: "round", strokeLinejoin: "round" }) }));
}
function ChevronDownIcon() {
    return (_jsx("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2.2", "aria-hidden": true, children: _jsx("path", { d: "M6 9l6 6 6-6", strokeLinecap: "round", strokeLinejoin: "round" }) }));
}
function CodeBlockToolbar({ expanded, copied, langLabel, position = "top", showExpand, onToggleExpand, onCopy, }) {
    return (_jsxs("div", { className: `alpha-router-code-block__toolbar${position === "bottom" ? " alpha-router-code-block__toolbar--bottom" : ""}`, children: [position === "top" ? _jsx("span", { className: "alpha-router-code-block__lang", children: langLabel }) : null, _jsxs("div", { className: "alpha-router-code-block__actions", children: [showExpand ? (_jsx("button", { type: "button", className: "alpha-router-code-block__action alpha-router-code-block__action--icon", "aria-label": expanded ? "Collapse code block" : "Expand code block", "aria-expanded": expanded, title: expanded ? "Collapse" : "Expand", onClick: onToggleExpand, children: expanded ? _jsx(ChevronUpIcon, {}) : _jsx(ChevronDownIcon, {}) })) : null, _jsx("button", { type: "button", className: "alpha-router-code-block__action alpha-router-code-block__action--copy", onClick: () => void onCopy(), children: copied ? "Copied" : "Copy" })] })] }));
}
function ChatCodeBlockInner({ code, language, variant = "code", deferHighlight = false }) {
    const rootRef = useRef(null);
    const [copied, setCopied] = useState(false);
    const lang = useMemo(() => normalizeLanguage(language), [language]);
    const stateKey = useMemo(() => codeBlockExpandStateKey(code, lang, variant), [code, lang, variant]);
    // Restore after remounts (e.g. chat scroll refresh remounts Markdown nodes).
    const [expanded, setExpanded] = useState(() => rememberedExpanded.get(stateKey) ?? false);
    const isOutput = variant === "output" || lang === "plaintext";
    const { preview, truncated } = useMemo(() => getCollapsedCodePreview(code, CODE_BLOCK_COLLAPSED_PREVIEW_LINES), [code]);
    const canCollapse = truncated;
    const showFull = expanded || !canCollapse;
    const visibleCode = showFull ? code : preview;
    const shouldHighlight = lang === "python" && !deferHighlight;
    const highlightedHtml = useMemo(() => (shouldHighlight ? highlightPython(visibleCode) : null), [visibleCode, shouldHighlight]);
    function toggleExpanded() {
        const root = rootRef.current;
        const scroller = findVerticalScrollParent(root);
        const beforeTop = root?.getBoundingClientRect().top ?? 0;
        const beforeScrollTop = scroller?.scrollTop ?? 0;
        setExpanded((open) => {
            const next = !open;
            rememberExpanded(stateKey, next);
            return next;
        });
        // Keep the block anchored in the viewport so expand does not jump scroll
        // (jump-to-top can remount messages and used to look like an auto-collapse).
        requestAnimationFrame(() => {
            if (!root || !scroller)
                return;
            const afterTop = root.getBoundingClientRect().top;
            const delta = afterTop - beforeTop;
            if (Math.abs(delta) > 0.5) {
                scroller.scrollTop = beforeScrollTop + delta;
            }
        });
    }
    async function onCopy() {
        if (!code)
            return;
        let ok = false;
        try {
            await navigator.clipboard.writeText(code);
            ok = true;
        }
        catch {
            ok = await copyTextToClipboard(code);
        }
        if (!ok)
            return;
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
    }
    const codeClassName = lang === "python"
        ? `alpha-router-code-block__code language-python${highlightedHtml ? " hljs" : ""}`
        : "alpha-router-code-block__code alpha-router-code-block__code--plain";
    const label = languageLabel(lang, variant);
    const collapsedPreview = canCollapse && !expanded;
    return (_jsxs("div", { ref: rootRef, className: `alpha-router-code-block${isOutput ? " alpha-router-code-block--output" : " alpha-router-code-block--python"}${collapsedPreview ? " alpha-router-code-block--collapsed" : ""}${collapsedPreview ? " alpha-router-code-block--truncated" : ""}`, dir: "ltr", children: [_jsx(CodeBlockToolbar, { expanded: expanded, copied: copied, langLabel: label, showExpand: canCollapse, onToggleExpand: toggleExpanded, onCopy: onCopy }), _jsx("div", { className: "alpha-router-code-block__body", children: _jsx("pre", { className: "alpha-router-code-block__pre", dir: "ltr", children: highlightedHtml ? (_jsx("code", { className: codeClassName, dir: "ltr", dangerouslySetInnerHTML: { __html: highlightedHtml } })) : (_jsx("code", { className: codeClassName, dir: "ltr", children: visibleCode })) }) }), expanded && canCollapse ? (_jsx(CodeBlockToolbar, { expanded: expanded, copied: copied, langLabel: label, position: "bottom", showExpand: true, onToggleExpand: toggleExpanded, onCopy: onCopy })) : null] }));
}
const ChatCodeBlock = memo(ChatCodeBlockInner);
export default ChatCodeBlock;
