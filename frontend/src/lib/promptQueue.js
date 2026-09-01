/** Show the full list inline only while the queue stays this small. */
export const PROMPT_QUEUE_INLINE_LIMIT = 2;
export function isPromptQueueCollapsed(opts) {
    if (opts.count <= 0 || opts.expanded)
        return false;
    return opts.count > (opts.inlineLimit ?? PROMPT_QUEUE_INLINE_LIMIT);
}
export function shouldShowPromptQueueBar(count, inlineLimit = PROMPT_QUEUE_INLINE_LIMIT) {
    return count > inlineLimit;
}
export function promptQueueCountLabel(count) {
    return count === 1 ? "1 in queue" : `${count} in queue`;
}
