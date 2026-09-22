import { useEffect, useMemo, useState } from "react";
import Modal from "../Modal";
import AuthenticatedImage from "../AuthenticatedImage";
import { fetchAttachmentPolicy, type AttachmentPolicy } from "../../lib/attachmentPolicy";
import { formatMediaBytes } from "../../lib/mediaLibrary";
import {
  attachSlotOverflowMessage,
  capAttachSelection,
  composerAttachEligibility,
  listComposerAttachMedia,
  mediaCandidatesToFiles,
  type ComposerAttachMediaCandidate,
} from "../../lib/composerAttachSources";

type Props = {
  open: boolean;
  projectId?: string | null;
  privateMode: boolean;
  remainingSlots: number;
  onClose: () => void;
  onPick: (files: File[]) => void | Promise<void>;
  onPickMediaIds?: (ids: number[]) => void | Promise<void>;
};

export default function ComposerMediaPicker({
  open,
  projectId,
  privateMode,
  remainingSlots,
  onClose,
  onPick,
  onPickMediaIds,
}: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ComposerAttachMediaCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelected([]);
    setError("");
    setFlash("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const delay = query.trim() ? 250 : 0;
    const handle = window.setTimeout(() => {
      setLoading(true);
      void listComposerAttachMedia({ projectId, query, limit: 60 })
        .then((res) => {
          if (cancelled) return;
          setItems(res.items);
          setTotal(res.total);
          setError("");
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [open, projectId, query]);

  const title = projectId ? "Attach from project Media" : "Attach from Media";

  // The operator's file type policy, so the picker greys out what the
  // server would refuse. Cached in the lib; null until it arrives.
  const [policy, setPolicy] = useState<AttachmentPolicy | null>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void fetchAttachmentPolicy().then((p) => {
      if (!cancelled) setPolicy(p);
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const rows = useMemo(
    () =>
      items.map((item) => ({
        item,
        eligibility: composerAttachEligibility(item, { privateMode, policy }),
      })),
    [items, privateMode, policy],
  );

  function toggle(id: number, attachable: boolean) {
    if (!attachable) return;
    const next = capAttachSelection(selected, id, remainingSlots);
    setSelected(next.ids);
    setFlash(next.blocked ? attachSlotOverflowMessage(remainingSlots) : "");
  }

  async function confirm() {
    const chosen = rows
      .filter((row) => selected.includes(row.item.id) && row.eligibility.attachable)
      .map((row) => row.item);
    if (!chosen.length || busy) return;
    setBusy(true);
    setError("");
    try {
      if (onPickMediaIds && !privateMode) {
        await onPickMediaIds(chosen.map((item) => item.id));
      } else {
        const files = await mediaCandidatesToFiles(chosen);
        await onPick(files);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      panelClassName="modal-panel--composer-media"
      headerActions={
        remainingSlots > 0 ? (
          <span className="alpha-router-media-picker__slots">
            {remainingSlots} slot{remainingSlots === 1 ? "" : "s"} left
          </span>
        ) : null
      }
    >
      {privateMode ? (
        <p className="alpha-router-media-picker__note">
          Private Mode can attach images and plain-text files only. Documents that need server
          extraction stay disabled.
        </p>
      ) : null}
      {remainingSlots <= 0 ? (
        <p className="alpha-router-media-picker__note">{attachSlotOverflowMessage(0)}</p>
      ) : null}
      <label className="alpha-router-media-picker__search">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search files"
          aria-label="Search media"
          // eslint-disable-next-line jsx-a11y/no-autofocus -- a picker the user just opened; focus belongs in its search field
          autoFocus
        />
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {flash ? <p className="alpha-router-media-picker__flash">{flash}</p> : null}
      {loading && !items.length ? <p className="muted-text">Loading media…</p> : null}
      {!loading && !items.length && !error ? (
        <p className="muted-text">
          {query.trim() ? "No media matches your search." : "No media files yet."}
        </p>
      ) : null}
      <div className="alpha-router-media-picker__grid">
        {rows.map(({ item, eligibility }) => {
          const checked = selected.includes(item.id);
          const disabled = !eligibility.attachable || (remainingSlots <= 0 && !checked);
          return (
            <button
              key={item.id}
              type="button"
              className={`alpha-router-media-picker__card${checked ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`}
              disabled={disabled && !checked}
              title={eligibility.reason || item.fileName}
              onClick={() => toggle(item.id, eligibility.attachable)}
            >
              <span className="alpha-router-media-picker__thumb">
                {item.kind === "image" ? (
                  <AuthenticatedImage url={item.url} alt={item.fileName} />
                ) : (
                  <span className="alpha-router-media-picker__kind">{item.kind || "file"}</span>
                )}
              </span>
              <span className="alpha-router-media-picker__name" title={item.fileName}>
                {item.fileName}
              </span>
              <span className="alpha-router-media-picker__meta">
                {item.sizeBytes != null ? formatMediaBytes(item.sizeBytes) : item.mimeType}
              </span>
            </button>
          );
        })}
      </div>
      {total > items.length ? (
        <p className="muted-text">Showing {items.length} of {total}. Search to find older files.</p>
      ) : null}
      <div className="alpha-router-media-picker__foot">
        <span className="muted-text">
          {selected.length ? `${selected.length} selected` : "Select files to attach"}
        </span>
        <div className="alpha-router-media-picker__actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => void confirm()}
            disabled={!selected.length || busy || remainingSlots <= 0}
          >
            {busy ? "Attaching…" : selected.length ? `Attach ${selected.length}` : "Attach"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
