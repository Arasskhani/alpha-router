import { useEffect } from "react";
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
  onConfirm: () => void;
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
  onConfirm,
  onCancel,
  onSecondary,
}: Props) {
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

  return createPortal(
    <div className="modal-overlay modal-overlay-confirm" onClick={onCancel} role="presentation">
      <div className="modal-panel modal-panel-confirm" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true">
        <div className="modal-header">
          <h3>{title}</h3>
        </div>
        <div className="modal-body">
          <p className="confirm-message">{renderedMessage}</p>
          <div className={`dialog-actions${secondaryLabel ? " dialog-actions-three" : ""}`}>
            <button
              type="button"
              className={danger ? "btn btn-danger" : "btn"}
              onClick={onConfirm}
              autoFocus
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
