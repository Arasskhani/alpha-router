import { memo, useMemo, useState } from "react";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import { copyTextToClipboard } from "../../lib/clipboard";

hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);

type Props = {
  code: string;
  language?: string;
  /** Execution log / stdout block from code interpreter. */
  variant?: "code" | "output";
  /** Keep plain text while the assistant message is still streaming. */
  deferHighlight?: boolean;
};

function normalizeLanguage(lang?: string): string {
  const raw = (lang || "").trim().toLowerCase();
  if (!raw) return "plaintext";
  if (raw === "py") return "python";
  if (raw === "text" || raw === "console" || raw === "output") return "plaintext";
  return raw;
}

function languageLabel(lang: string, variant: Props["variant"]): string {
  if (variant === "output") return "Output";
  if (lang === "python") return "Python";
  if (lang === "plaintext") return "Code";
  return lang;
}

function highlightPython(code: string): string | null {
  if (!code) return null;
  try {
    return hljs.highlight(code, { language: "python", ignoreIllegals: true }).value;
  } catch {
    return null;
  }
}

function ChevronUpIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
      <path d="M18 15l-6-6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type CodeBlockToolbarProps = {
  expanded: boolean;
  copied: boolean;
  langLabel: string;
  position?: "top" | "bottom";
  onToggleExpand: () => void;
  onCopy: () => void;
};

function CodeBlockToolbar({
  expanded,
  copied,
  langLabel,
  position = "top",
  onToggleExpand,
  onCopy,
}: CodeBlockToolbarProps) {
  return (
    <div
      className={`alpha-router-code-block__toolbar${position === "bottom" ? " alpha-router-code-block__toolbar--bottom" : ""}`}
    >
      {position === "top" ? <span className="alpha-router-code-block__lang">{langLabel}</span> : null}
      <div className="alpha-router-code-block__actions">
        <button
          type="button"
          className="alpha-router-code-block__action alpha-router-code-block__action--icon"
          aria-label={expanded ? "Collapse code block" : "Expand code block"}
          aria-expanded={expanded}
          title={expanded ? "Collapse" : "Expand"}
          onClick={onToggleExpand}
        >
          {expanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
        </button>
        <button type="button" className="alpha-router-code-block__action alpha-router-code-block__action--copy" onClick={() => void onCopy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function ChatCodeBlockInner({ code, language, variant = "code", deferHighlight = false }: Props) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const lang = useMemo(() => normalizeLanguage(language), [language]);
  const isOutput = variant === "output" || lang === "plaintext";
  const shouldHighlight = lang === "python" && !deferHighlight;
  const highlightedHtml = useMemo(
    () => (shouldHighlight ? highlightPython(code) : null),
    [code, shouldHighlight],
  );

  async function onCopy() {
    if (!code) return;
    let ok = false;
    try {
      await navigator.clipboard.writeText(code);
      ok = true;
    } catch {
      ok = await copyTextToClipboard(code);
    }
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  const codeClassName =
    lang === "python"
      ? `alpha-router-code-block__code language-python${highlightedHtml ? " hljs" : ""}`
      : "alpha-router-code-block__code alpha-router-code-block__code--plain";
  const label = languageLabel(lang, variant);

  return (
    <div
      className={`alpha-router-code-block${isOutput ? " alpha-router-code-block--output" : " alpha-router-code-block--python"}${expanded ? "" : " alpha-router-code-block--collapsed"}`}
      dir="ltr"
    >
      <CodeBlockToolbar
        expanded={expanded}
        copied={copied}
        langLabel={label}
        onToggleExpand={() => setExpanded((open) => !open)}
        onCopy={onCopy}
      />
      <pre className="alpha-router-code-block__pre" dir="ltr">
        {highlightedHtml ? (
          <code
            className={codeClassName}
            dir="ltr"
            dangerouslySetInnerHTML={{ __html: highlightedHtml }}
          />
        ) : (
          <code className={codeClassName} dir="ltr">
            {code}
          </code>
        )}
      </pre>
      {expanded ? (
        <CodeBlockToolbar
          expanded={expanded}
          copied={copied}
          langLabel={label}
          position="bottom"
          onToggleExpand={() => setExpanded((open) => !open)}
          onCopy={onCopy}
        />
      ) : null}
    </div>
  );
}

const ChatCodeBlock = memo(ChatCodeBlockInner);
export default ChatCodeBlock;
