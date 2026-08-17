import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  open: boolean;
  title: string;
  message: string;
  emphasize?: string;
  emphasizeDanger?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
  secondaryLabel?: string;
  danger?: boolean;
  promptLabel?: string;
  promptDefault?: string;
  promptRequired?: boolean;
  promptExactMatch?: string;
  onConfirm: (promptValue?: string) => void;
  onCancel: () => void;
  onSecondary?: () => void;
};

export default function ConfirmModal({
  open,
  title,
  message,
  emphasize,
  emphasizeDanger = false,
  confirmLabel = "Yes",
  cancelLabel = "No",
  secondaryLabel,
  danger = false,
  promptLabel,
  promptDefault = "",
  promptRequired = false,
  promptExactMatch,
  onConfirm,
  onCancel,
  onSecondary,
}: Props) {
  const [promptValue, setPromptValue] = useState(promptDefault);

  useEffect(() => {
    if (open) setPromptValue(promptDefault);
  }, [open, promptDefault]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const emphasisIndex = emphasize ? message.indexOf(emphasize) : -1;
  const renderedMessage =
    emphasize && emphasisIndex >= 0 ? (
      <>
        {message.slice(0, emphasisIndex)}
        <strong className={emphasizeDanger ? "confirm-message__emphasis--danger" : undefined}>
          {emphasize}
        </strong>
        {message.slice(emphasisIndex + emphasize.length)}
      </>
    ) : (
      message
    );
  const trimmed = promptValue.trim();
  const confirmDisabled = promptExactMatch
    ? trimmed !== promptExactMatch
    : Boolean(promptLabel && promptRequired && !trimmed);

  return createPortal(
    <div className="modal-overlay modal-overlay-confirm" onClick={onCancel} role="presentation">
      <div className="modal-panel modal-panel-confirm" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true">
        <div className="modal-header">
          <h3>{title}</h3>
        </div>
        <div className="modal-body">
          <p className="confirm-message">{renderedMessage}</p>
          {promptLabel ? (
            <label className="confirm-prompt">
              <span>{promptLabel}</span>
              <input
                type="text"
                value={promptValue}
                onChange={(e) => setPromptValue(e.target.value)}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !confirmDisabled) {
                    e.preventDefault();
                    onConfirm(trimmed);
                  }
                }}
              />
            </label>
          ) : null}
          <div className={`dialog-actions${secondaryLabel ? " dialog-actions-three" : ""}`}>
            <button
              type="button"
              className={danger ? "btn btn-danger" : "btn"}
              onClick={() => onConfirm(promptLabel ? trimmed : undefined)}
              disabled={confirmDisabled}
              autoFocus={!promptLabel}
            >
              {confirmLabel}
            </button>
            {secondaryLabel && onSecondary ? (
              <button type="button" className="btn btn-ghost" onClick={onSecondary}>
                {secondaryLabel}
              </button>
            ) : null}
            <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onCancel}>
              {cancelLabel}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
