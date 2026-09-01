import { jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { createContext, useContext } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatCodeBlock from "./chat/ChatCodeBlock";
import { inertBrowserUrl, safeBrowserUrl } from "../lib/browserUrlPolicy";
import { fetchAuthenticatedMediaBlob, isAlphaRouterMediaFileUrl } from "../lib/mediaUrl";
const MarkdownStreamingContext = createContext(false);
function stripTrailingNewline(raw) {
    return raw.replace(/\n$/, "");
}
function linkText(children) {
    if (typeof children === "string" || typeof children === "number")
        return String(children);
    if (Array.isArray(children))
        return children.map(linkText).join("");
    return "download";
}
export async function downloadAuthenticatedMedia(url, fileName) {
    const blob = await fetchAuthenticatedMediaBlob(url);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = fileName || "download";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}
function SafeLink({ href, children, onClick, ...props }) {
    const safeHref = inertBrowserUrl(href, "navigation");
    const authenticatedMedia = Boolean(href && isAlphaRouterMediaFileUrl(href));
    function handleClick(event) {
        onClick?.(event);
        if (event.defaultPrevented || !authenticatedMedia || !href)
            return;
        event.preventDefault();
        void downloadAuthenticatedMedia(href, linkText(children)).catch((error) => {
            console.error("Authenticated media download failed", error);
        });
    }
    return (_jsx("a", { href: safeHref, target: "_blank", rel: "noopener noreferrer", onClick: handleClick, ...props, children: children }));
}
function SafeImage({ src, alt, ...props }) {
    return _jsx("img", { src: safeBrowserUrl(src, "image") ?? "", alt: alt ?? "", ...props });
}
function MarkdownCode({ className, children, ...props }) {
    const parentStreaming = useContext(MarkdownStreamingContext);
    const match = /language-([\w-]+)/i.exec(className || "");
    const lang = match?.[1]?.toLowerCase();
    const code = stripTrailingNewline(String(children ?? ""));
    const isBlock = Boolean(lang) || code.includes("\n");
    if (!isBlock) {
        return (_jsx("code", { className: `md-inline-code${className ? ` ${className}` : ""}`, dir: "ltr", ...props, children: children }));
    }
    const variant = lang === "text" || lang === "console" || lang === "output" ? "output" : "code";
    return _jsx(ChatCodeBlock, { code: code, language: lang, variant: variant, deferHighlight: parentStreaming });
}
/** Render assistant / AI text as GitHub-flavored Markdown. */
export default function MarkdownContent({ content, className = "", streaming = false }) {
    if (!content)
        return null;
    return (_jsx(MarkdownStreamingContext.Provider, { value: streaming, children: _jsx("div", { className: `markdown-body${className ? ` ${className}` : ""}`, children: _jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], components: {
                    pre: ({ children }) => _jsx(_Fragment, { children: children }),
                    code: MarkdownCode,
                    a: SafeLink,
                    img: SafeImage,
                }, children: content }) }) }));
}
