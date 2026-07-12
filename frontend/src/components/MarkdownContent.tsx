import { createContext, useContext } from "react";
import type { ComponentPropsWithoutRef } from "react";
import type { ExtraProps } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatCodeBlock from "./chat/ChatCodeBlock";

type Props = {
  content: string;
  className?: string;
  /** When true, code blocks stay plain text until streaming finishes (reduces layout jump). */
  streaming?: boolean;
};

const MarkdownStreamingContext = createContext(false);

function stripTrailingNewline(raw: string): string {
  return raw.replace(/\n$/, "");
}

/**
 * Block dangerous URL schemes on markdown links/images.
 *
 * react-markdown v10 escapes raw HTML by default, so the remaining XSS vector
 * is a ``javascript:`` (or ``vbscript:`` / ``data:``) URL in a link or image
 * ``src``/``href``. We allow ``http:``, ``https:``, ``mailto:``, ``tel:``, and
 * ``data:image/...`` (inline images); everything else is rewritten to ``#`` so
 * the element renders but is inert.
 */
function safeUrl(url: string | undefined): string {
  if (!url) return "";
  const trimmed = url.trim();
  if (/^\s*javascript:/i.test(trimmed)) return "#";
  if (/^\s*vbscript:/i.test(trimmed)) return "#";
  if (/^\s*data:/i.test(trimmed) && !/^\s*data:image\//i.test(trimmed)) return "#";
  return url;
}

function SafeLink({
  href,
  children,
  ...props
}: ComponentPropsWithoutRef<"a"> & ExtraProps) {
  return (
    <a href={safeUrl(href ?? undefined)} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  );
}

function SafeImage({
  src,
  alt,
  ...props
}: ComponentPropsWithoutRef<"img"> & ExtraProps) {
  return <img src={safeUrl(src ?? undefined)} alt={alt ?? ""} {...props} />;
}

function MarkdownCode({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<"code"> & ExtraProps) {
  const parentStreaming = useContext(MarkdownStreamingContext);
  const match = /language-([\w-]+)/i.exec(className || "");
  const lang = match?.[1]?.toLowerCase();
  const code = stripTrailingNewline(String(children ?? ""));
  const isBlock = Boolean(lang) || code.includes("\n");

  if (!isBlock) {
    return (
      <code className={`md-inline-code${className ? ` ${className}` : ""}`} dir="ltr" {...props}>
        {children}
      </code>
    );
  }

  const variant = lang === "text" || lang === "console" || lang === "output" ? "output" : "code";
  return <ChatCodeBlock code={code} language={lang} variant={variant} deferHighlight={parentStreaming} />;
}

/** Render assistant / AI text as GitHub-flavored Markdown. */
export default function MarkdownContent({ content, className = "", streaming = false }: Props) {
  if (!content) return null;

  return (
    <MarkdownStreamingContext.Provider value={streaming}>
      <div className={`markdown-body${className ? ` ${className}` : ""}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            pre: ({ children }) => <>{children}</>,
            code: MarkdownCode,
            a: SafeLink,
            img: SafeImage,
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </MarkdownStreamingContext.Provider>
  );
}
