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
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </MarkdownStreamingContext.Provider>
  );
}
