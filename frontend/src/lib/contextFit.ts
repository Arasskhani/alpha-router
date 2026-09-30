/**
 * What the server left out of a turn to fit the model's context window.
 *
 * A chat longer than the model's window is fitted before it is sent: the
 * newest messages go word for word and the oldest give way, to the chat's
 * summary or with a note to the model. The answer says so, under its label.
 */

export type ContextFit = { dropped: number; summarized: number };

export function readContextFit(value: unknown): ContextFit | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  const dropped = Number(raw.dropped);
  const summarized = Number(raw.summarized ?? 0);
  if (!Number.isInteger(dropped) || dropped <= 0) return undefined;
  return { dropped, summarized: Number.isInteger(summarized) && summarized > 0 ? Math.min(summarized, dropped) : 0 };
}

/** The line under the answer's label. */
export function contextFitLabel(fit: ContextFit): string {
  const left = fit.dropped - fit.summarized;
  if (fit.summarized && !left) return "Older messages read as a summary, to fit the model";
  if (fit.summarized) return `Older messages read as a summary; ${left} more left out, to fit the model`;
  return `${fit.dropped} older message${fit.dropped === 1 ? "" : "s"} left out, to fit the model`;
}

/** What it means, opened from the label. */
export function contextFitNote(fit: ContextFit): string {
  return (
    "This chat is longer than the model's context window. The newest messages were sent word for word; " +
    (fit.summarized
      ? `the ${fit.summarized} oldest were sent as a summary${fit.dropped > fit.summarized ? ` and ${fit.dropped - fit.summarized} were left out` : ""}.`
      : `the ${fit.dropped} oldest were left out.`)
  );
}
