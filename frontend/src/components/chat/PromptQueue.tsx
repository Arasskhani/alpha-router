import {
  isPromptQueueCollapsed,
  promptQueueCountLabel,
  shouldShowPromptQueueBar,
} from "../../lib/promptQueue";

export type PromptQueueViewItem = {
  id: string;
  preview: string;
};

type Props = {
  items: PromptQueueViewItem[];
  expanded: boolean;
  onToggleExpanded: () => void;
  onEdit: (id: string) => void;
  onRemove: (id: string) => void;
  onClearAll: () => void;
};

export default function PromptQueue({
  items,
  expanded,
  onToggleExpanded,
  onEdit,
  onRemove,
  onClearAll,
}: Props) {
  if (!items.length) return null;

  const collapsed = isPromptQueueCollapsed({ count: items.length, expanded });
  const showBar = shouldShowPromptQueueBar(items.length);
  const nextPreview = items[0]?.preview ?? "";

  return (
    <div className="alpha-router-prompt-queue" aria-label="Queued messages">
      {showBar ? (
        <div className="alpha-router-prompt-queue__bar">
          <span className="alpha-router-prompt-queue__count">{promptQueueCountLabel(items.length)}</span>
          {collapsed ? (
            <span className="alpha-router-prompt-queue__next" title={nextPreview}>
              Next: {nextPreview}
            </span>
          ) : (
            <span className="alpha-router-prompt-queue__next" aria-hidden />
          )}
          <div className="alpha-router-prompt-queue__actions">
            <button
              type="button"
              className="alpha-router-prompt-queue__btn alpha-router-prompt-queue__btn--text"
              onClick={onToggleExpanded}
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Show queued messages" : "Hide queued messages"}
              title={collapsed ? "Show queue" : "Hide queue"}
            >
              {collapsed ? "Show" : "Hide"}
            </button>
            <button
              type="button"
              className="alpha-router-prompt-queue__btn alpha-router-prompt-queue__btn--text"
              onClick={onClearAll}
              aria-label="Clear queued messages"
              title="Clear all"
            >
              Clear
            </button>
          </div>
        </div>
      ) : null}
      {collapsed ? null : (
        <div className="alpha-router-prompt-queue__list">
          {items.map((item, idx) => (
            <div key={item.id} className="alpha-router-prompt-queue__item">
              <span className="alpha-router-prompt-queue__index" aria-hidden>
                {idx + 1}
              </span>
              <span className="alpha-router-prompt-queue__text" title={item.preview}>
                {item.preview}
              </span>
              <div className="alpha-router-prompt-queue__actions">
                <button
                  type="button"
                  className="alpha-router-prompt-queue__btn"
                  onClick={() => onEdit(item.id)}
                  aria-label="Edit queued message"
                  title="Edit"
                >
                  ✎
                </button>
                <button
                  type="button"
                  className="alpha-router-prompt-queue__btn alpha-router-prompt-queue__btn--remove"
                  onClick={() => onRemove(item.id)}
                  aria-label="Remove from queue"
                  title="Remove"
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
