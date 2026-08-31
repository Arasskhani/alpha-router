/** Show the full list inline only while the queue stays this small. */
export const PROMPT_QUEUE_INLINE_LIMIT = 2;

export function isPromptQueueCollapsed(opts: {
  count: number;
  expanded: boolean;
  inlineLimit?: number;
}): boolean {
  if (opts.count <= 0 || opts.expanded) return false;
  return opts.count > (opts.inlineLimit ?? PROMPT_QUEUE_INLINE_LIMIT);
}

export function shouldShowPromptQueueBar(count: number, inlineLimit = PROMPT_QUEUE_INLINE_LIMIT): boolean {
  return count > inlineLimit;
}

export function promptQueueCountLabel(count: number): string {
  return count === 1 ? "1 in queue" : `${count} in queue`;
}
