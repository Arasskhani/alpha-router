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
const rememberedExpanded = new Map<string, boolean>();

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

/** Visible slice for a collapsed block; full `code` stays available for Copy. */
export function getCollapsedCodePreview(
  code: string,
  maxLines: number = CODE_BLOCK_COLLAPSED_PREVIEW_LINES,
): { preview: string; truncated: boolean } {
  if (!code) return { preview: "", truncated: false };
  const lines = code.split("\n");
  if (lines.length <= maxLines) {
    return { preview: code, truncated: false };
  }
  return {
    preview: lines.slice(0, maxLines).join("\n"),
    truncated: true,
  };
}

function hashString(value: string): string {
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
export function codeBlockExpandStateKey(
  code: string,
  language: string,
  variant: string,
): string {
  const { preview } = getCollapsedCodePreview(code);
  return `${variant}|${language}|${hashString(preview)}`;
}

function rememberExpanded(key: string, expanded: boolean): void {
  if (rememberedExpanded.has(key)) rememberedExpanded.delete(key);
  rememberedExpanded.set(key, expanded);
  while (rememberedExpanded.size > MAX_REMEMBERED_EXPAND_STATES) {
    const oldest = rememberedExpanded.keys().next().value;
    if (oldest == null) break;
    rememberedExpanded.delete(oldest);
  }
}

function findVerticalScrollParent(node: HTMLElement | null): HTMLElement | null {
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
  showExpand: boolean;
  onToggleExpand: () => void;
  onCopy: () => void;
};

function CodeBlockToolbar({
  expanded,
  copied,
  langLabel,
  position = "top",
  showExpand,
  onToggleExpand,
  onCopy,
}: CodeBlockToolbarProps) {
  return (
    <div
      className={`alpha-router-code-block__toolbar${position === "bottom" ? " alpha-router-code-block__toolbar--bottom" : ""}`}
    >
      {position === "top" ? <span className="alpha-router-code-block__lang">{langLabel}</span> : null}
      <div className="alpha-router-code-block__actions">
        {showExpand ? (
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
        ) : null}
        <button type="button" className="alpha-router-code-block__action alpha-router-code-block__action--copy" onClick={() => void onCopy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function ChatCodeBlockInner({ code, language, variant = "code", deferHighlight = false }: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [copied, setCopied] = useState(false);
  const lang = useMemo(() => normalizeLanguage(language), [language]);
  const stateKey = useMemo(
    () => codeBlockExpandStateKey(code, lang, variant),
    [code, lang, variant],
  );
  // Restore after remounts (e.g. chat scroll refresh remounts Markdown nodes).
  const [expanded, setExpanded] = useState(() => rememberedExpanded.get(stateKey) ?? false);
  const isOutput = variant === "output" || lang === "plaintext";
  const { preview, truncated } = useMemo(
    () => getCollapsedCodePreview(code, CODE_BLOCK_COLLAPSED_PREVIEW_LINES),
    [code],
  );
  const canCollapse = truncated;
  const showFull = expanded || !canCollapse;
  const visibleCode = showFull ? code : preview;
  const shouldHighlight = lang === "python" && !deferHighlight;
  const highlightedHtml = useMemo(
    () => (shouldHighlight ? highlightPython(visibleCode) : null),
    [visibleCode, shouldHighlight],
  );

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
      if (!root || !scroller) return;
      const afterTop = root.getBoundingClientRect().top;
      const delta = afterTop - beforeTop;
      if (Math.abs(delta) > 0.5) {
        scroller.scrollTop = beforeScrollTop + delta;
      }
    });
  }

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
  const collapsedPreview = canCollapse && !expanded;

  return (
    <div
      ref={rootRef}
      className={`alpha-router-code-block${isOutput ? " alpha-router-code-block--output" : " alpha-router-code-block--python"}${collapsedPreview ? " alpha-router-code-block--collapsed" : ""}${collapsedPreview ? " alpha-router-code-block--truncated" : ""}`}
      dir="ltr"
    >
      <CodeBlockToolbar
        expanded={expanded}
        copied={copied}
        langLabel={label}
        showExpand={canCollapse}
        onToggleExpand={toggleExpanded}
        onCopy={onCopy}
      />
      <div className="alpha-router-code-block__body">
        <pre className="alpha-router-code-block__pre" dir="ltr">
          {highlightedHtml ? (
            <code
              className={codeClassName}
              dir="ltr"
              dangerouslySetInnerHTML={{ __html: highlightedHtml }}
            />
          ) : (
            <code className={codeClassName} dir="ltr">
              {visibleCode}
            </code>
          )}
        </pre>
      </div>
      {expanded && canCollapse ? (
        <CodeBlockToolbar
          expanded={expanded}
          copied={copied}
          langLabel={label}
          position="bottom"
          showExpand
          onToggleExpand={toggleExpanded}
          onCopy={onCopy}
        />
      ) : null}
    </div>
  );
}

const ChatCodeBlock = memo(ChatCodeBlockInner);
export default ChatCodeBlock;
