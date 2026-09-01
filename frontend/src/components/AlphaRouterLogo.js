import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { PRODUCT_NAME, PRODUCT_NAME_MARKED, TRADEMARK_SYMBOL } from "../lib/brand";
function TrademarkSign() {
    return (_jsx("span", { className: "alpha-router-logo-tm", "aria-hidden": true, children: TRADEMARK_SYMBOL }));
}
const MARK_URL = "/alpha-router-mark.png?v=7";
const MARK_URL_HARD = "/alpha-router-mark-hard.png?v=7";
/** Wordmark: optional mark-as-A + remaining letters. */
export default function AlphaRouterLogo({ size = 32, className = "", showMark = false, splitWords = false, joined = false, showTrademark = true, }) {
    const wordSize = Math.round(size * 0.86);
    /* Joined login: mark reads as display cap above lowercase. */
    const markSize = Math.max(12, Math.round(wordSize * (joined ? 1.216 : 0.874)));
    const [, ...rest] = PRODUCT_NAME.split(/\s+/);
    const routerWord = rest.join(" ") || "Router";
    const routerText = joined ? routerWord.toLowerCase() : routerWord;
    const alphaRest = showMark ? "lpha" : null;
    /* Joined assemble: full lowercase rest after the mark. */
    const joinedRest = `lpha${routerText}`;
    const markUrl = className.includes("topbar") ? MARK_URL_HARD : MARK_URL;
    const mark = showMark ? (_jsx("span", { className: "alpha-router-logo-mark", "aria-hidden": true, style: joined
            ? { ["--alpha-mark-url"]: `url(${markUrl})` }
            : {
                width: markSize,
                height: markSize,
                ["--alpha-mark-url"]: `url(${markUrl})`,
            } })) : null;
    const wordClass = [
        "alpha-router-logo-word",
        showMark ? "alpha-router-logo-word--mark-as-a" : "",
        joined ? "alpha-router-logo-word--joined" : "",
        className,
    ]
        .filter(Boolean)
        .join(" ");
    return (_jsxs("span", { className: wordClass, "aria-label": showTrademark ? PRODUCT_NAME_MARKED : PRODUCT_NAME, style: { fontSize: `${wordSize}px`, lineHeight: `${size}px` }, children: [joined && showMark && splitWords ? (
            /* Login: A first, then “lpharouter” drops in from above */
            _jsxs("span", { className: "alpha-router-logo-tail alpha-router-logo-tail--split", children: [_jsx("span", { className: "alpha-router-logo-part alpha-router-logo-part--mark", children: mark }), _jsx("span", { className: "alpha-router-logo-part alpha-router-logo-part--rest", children: joinedRest })] })) : splitWords ? (_jsxs("span", { className: "alpha-router-logo-tail alpha-router-logo-tail--split", children: [_jsx("span", { className: "alpha-router-logo-part alpha-router-logo-part--alpha", children: showMark ? (_jsxs("span", { className: "alpha-router-logo-alpha", children: [mark, _jsx("span", { className: "alpha-router-logo-alpha-rest", children: alphaRest })] })) : (_jsx("span", { className: "alpha-router-logo-alpha", children: "Alpha" })) }), _jsx("span", { className: "alpha-router-logo-part alpha-router-logo-part--gap", "aria-hidden": true, children: "\u00A0" }), _jsx("span", { className: "alpha-router-logo-part alpha-router-logo-part--router", children: routerText })] })) : (_jsxs("span", { className: "alpha-router-logo-tail", children: [showMark ? (_jsxs("span", { className: "alpha-router-logo-alpha", children: [mark, _jsx("span", { className: "alpha-router-logo-alpha-rest", children: alphaRest })] })) : (_jsx("span", { className: "alpha-router-logo-alpha", children: joined ? "alpha" : "Alpha" })), joined ? null : "\u00A0", routerText] })), showTrademark ? _jsx(TrademarkSign, {}) : null] }));
}
