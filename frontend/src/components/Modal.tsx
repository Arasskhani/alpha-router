import { ReactNode, useEffect } from "react";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** When true, header shows only the close control (no title bar text). */
  compactHeader?: boolean;
  /** When false, clicking the backdrop does not close the modal. */
  closeOnBackdrop?: boolean;
  /** When false, Escape does not close the modal. */
  closeOnEscape?: boolean;
};

export default function Modal({
  open,
  title,
  onClose,
  children,
  compactHeader,
  closeOnBackdrop = true,
  closeOnEscape = true,
}: Props) {
  useEffect(() => {
    if (!open || !closeOnEscape) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, closeOnEscape]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      onClick={closeOnBackdrop ? onClose : undefined}
      role="presentation"
    >
      <div className="modal-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className={`modal-header${compactHeader ? " modal-header--compact" : ""}`}>
          {compactHeader || !title ? <span aria-hidden="true" /> : <h3>{title}</h3>}
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
