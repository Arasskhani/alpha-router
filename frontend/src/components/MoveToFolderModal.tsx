import { useEffect, useMemo, useState, type CSSProperties } from "react";
import Modal from "./Modal";
import { IconFolder } from "./icons/navIcons";
import type { ChatFolder } from "../lib/chatStorage";

type Props = {
  open: boolean;
  folders: ChatFolder[];
  currentFolderId: string | null;
  onClose: () => void;
  onMove: (folderId: string | null) => void;
};

export default function MoveToFolderModal({
  open,
  folders,
  currentFolderId,
  onClose,
  onMove,
}: Props) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (open) setQuery("");
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return folders;
    return folders.filter((f) => (f.name || "").toLowerCase().includes(q));
  }, [folders, query]);

  return (
    <Modal
      open={open}
      title="Move to folder"
      onClose={onClose}
      panelClassName="modal-panel--move-folder"
      bodyClassName="modal-body--move-folder"
    >
      <div className="move-folder">
        <input
          type="search"
          className="move-folder__search"
          placeholder="Search folders…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          // eslint-disable-next-line jsx-a11y/no-autofocus -- a dialog the user just opened; the dialog pattern moves focus into it
          autoFocus
          aria-label="Search folders"
        />
        <div className="move-folder__list" role="listbox" aria-label="Folders">
          <button
            type="button"
            role="option"
            aria-selected={currentFolderId == null}
            className={`move-folder__item${currentFolderId == null ? " is-current" : ""}`}
            onClick={() => {
              onMove(null);
              onClose();
            }}
          >
            <span className="move-folder__item-icon" aria-hidden>
              <IconFolder />
            </span>
            <span className="move-folder__item-label">No folder</span>
            {currentFolderId == null ? <span className="move-folder__check">✓</span> : null}
          </button>
          {filtered.map((f) => {
            const selected = currentFolderId === f.id;
            return (
              <button
                key={f.id}
                type="button"
                role="option"
                aria-selected={selected}
                className={`move-folder__item${selected ? " is-current" : ""}`}
                style={f.color ? ({ ["--folder-accent"]: f.color } as CSSProperties) : undefined}
                onClick={() => {
                  onMove(f.id);
                  onClose();
                }}
              >
                <span className="move-folder__item-icon" aria-hidden>
                  <IconFolder />
                </span>
                <span className="move-folder__item-label">{f.name}</span>
                {selected ? <span className="move-folder__check">✓</span> : null}
              </button>
            );
          })}
          {filtered.length === 0 ? (
            <p className="move-folder__empty muted-text">No folders match</p>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}
