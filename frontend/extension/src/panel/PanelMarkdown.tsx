import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown for the side panel's answers.
 *
 * Links open in a new tab and only for http(s) and mailto. Images are never
 * loaded: an answer is shown as a link to the image instead. A model reading
 * a web page can be talked into writing an image whose address carries that
 * page's text; loading it would hand the text to whoever runs that address.
 * Raw HTML in an answer is dropped, not rendered.
 */

function safeHref(href: unknown): string | undefined {
  if (typeof href !== "string" || !href.trim()) return undefined;
  try {
    const url = new URL(href);
    return url.protocol === "https:" || url.protocol === "http:" || url.protocol === "mailto:" ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

export default function PanelMarkdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => {
            const safe = safeHref(href);
            return safe ? (
              <a href={safe} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            );
          },
          img: ({ src, alt }) => {
            const safe = safeHref(src);
            const label = alt ? `Image: ${alt}` : "Image";
            return safe ? (
              <a href={safe} target="_blank" rel="noopener noreferrer" className="markdown__image-link">
                {label}
              </a>
            ) : (
              <span>{label}</span>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
