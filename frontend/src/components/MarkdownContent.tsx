import { createContext, memo, useContext } from "react";
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
  /**
   * "link" shows every image as a link instead of loading it: for an answer
   * built from untrusted text, whose image address could carry data away.
   */
  images?: "load" | "link";
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

function ImageAsLink({ src, alt }: ComponentPropsWithoutRef<"img"> & ExtraProps) {
  const label = (alt ?? "").trim() || "open";
  return (
    <a
      href={inertBrowserUrl(typeof src === "string" ? src : undefined, "navigation")}
      target="_blank"
      rel="noopener noreferrer"
      className="md-image-link"
    >
      Image: {label}
    </a>
  );
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

// Module-level so their identity is stable: a new `components`/`remarkPlugins`
// object per render made react-markdown re-create every element of every
// message whenever the chat re-rendered (each streamed token).
const REMARK_PLUGINS = [remarkGfm];
const MARKDOWN_COMPONENTS = {
  pre: ({ children }: { children?: ReactNode }) => <>{children}</>,
  code: MarkdownCode,
  a: SafeLink,
  img: SafeImage,
};
const MARKDOWN_COMPONENTS_IMAGES_AS_LINKS = { ...MARKDOWN_COMPONENTS, img: ImageAsLink };

/** Render assistant / AI text as GitHub-flavored Markdown. */
function MarkdownContent({ content, className = "", streaming = false, images = "load" }: Props) {
  if (!content) return null;

  return (
    <MarkdownStreamingContext.Provider value={streaming}>
      <div className={`markdown-body${className ? ` ${className}` : ""}`}>
        <ReactMarkdown
          remarkPlugins={REMARK_PLUGINS}
          components={images === "link" ? MARKDOWN_COMPONENTS_IMAGES_AS_LINKS : MARKDOWN_COMPONENTS}
        >
          {content}
        </ReactMarkdown>
      </div>
    </MarkdownStreamingContext.Provider>
  );
}

// Finished messages have identical props from one chat render to the next;
// memo keeps their Markdown trees untouched while a sibling is streaming.
export default memo(MarkdownContent);
