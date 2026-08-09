import { createContext, useContext } from "react";
import type { ComponentPropsWithoutRef, MouseEvent, ReactNode } from "react";
import type { ExtraProps } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatCodeBlock from "./chat/ChatCodeBlock";
import { inertBrowserUrl, safeBrowserUrl } from "../lib/browserUrlPolicy";
import { fetchAuthenticatedMediaBlob, isAlphaRouterMediaFileUrl } from "../lib/mediaUrl";

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

function linkText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(linkText).join("");
  return "download";
}

export async function downloadAuthenticatedMedia(url: string, fileName: string): Promise<void> {
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

function SafeLink({
  href,
  children,
  onClick,
  ...props
}: ComponentPropsWithoutRef<"a"> & ExtraProps) {
  const safeHref = inertBrowserUrl(href, "navigation");
  const authenticatedMedia = Boolean(href && isAlphaRouterMediaFileUrl(href));

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || !authenticatedMedia || !href) return;
    event.preventDefault();
    void downloadAuthenticatedMedia(href, linkText(children)).catch((error) => {
      console.error("Authenticated media download failed", error);
    });
  }

  return (
    <a
      href={safeHref}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      {...props}
    >
      {children}
    </a>
  );
}

function SafeImage({
  src,
  alt,
  ...props
}: ComponentPropsWithoutRef<"img"> & ExtraProps) {
  return <img src={safeBrowserUrl(src, "image") ?? ""} alt={alt ?? ""} {...props} />;
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
