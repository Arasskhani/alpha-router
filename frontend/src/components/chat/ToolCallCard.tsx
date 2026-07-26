/**
 * ToolCallCard — renders a connector tool invocation inside the chat stream.
 *
 * Today the backend streams tool progress as plain content deltas
 * (e.g. "\n\nCalling gmail.search…\n\n"), which the existing SSE parser
 * already renders inline as text. This component is provided for a future,
 * richer rendering where the backend emits a structured `tool_call` SSE
 * event with provider, tool name, arguments, and result. It is intentionally
 * presentational and free of secrets — only provider/tool names and a
 * truncated result are shown.
 */

type Props = {
  provider: string;
  tool: string;
  argumentsPreview?: string;
  resultPreview?: string;
  status?: "running" | "done" | "error";
};

export default function ToolCallCard({ provider, tool, argumentsPreview, resultPreview, status = "running" }: Props) {
  return (
    <div className={`tool-call-card${status === "error" ? " error" : status === "done" ? " done" : ""}`} role="status">
      <div className="tool-call-card__head">
        <span className="tool-call-card__icon" aria-hidden="true">⚙</span>
        <span className="tool-call-card__title">
          <strong>{provider}</strong>.{tool}
        </span>
        <span className="tool-call-card__status">{status}</span>
      </div>
      {argumentsPreview && (
        <pre className="tool-call-card__args">{argumentsPreview}</pre>
      )}
      {resultPreview && (
        <pre className="tool-call-card__result">{resultPreview}</pre>
      )}
    </div>
  );
}
