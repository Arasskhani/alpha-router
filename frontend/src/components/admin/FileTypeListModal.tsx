import { ClipboardEvent, FormEvent, KeyboardEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, formatApiError } from "../../api";
import { type ConfirmOptions, useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import {
  EXTENSION_PATTERN,
  MAX_LIST_ENTRIES,
  diffLists,
  filterExtensions,
  isDefaultType,
  normalizeExtensionInput,
  normalizeSearchQuery,
  type FileTypeListKey,
  type FileTypePolicy,
} from "../../lib/fileTypePolicy";
import Modal from "../Modal";

/**
 * One of the two upload file-type lists, opened from the Storage Management
 * card: search it, add to it, take entries off it, then save.
 *
 * Nothing reaches the server until Save. Until then a removed entry stays on
 * screen struck through with an Undo, an added one is tagged "new", and
 * leaving with changes asks first — a list that decides what may enter the
 * platform should not change because a click landed on the wrong row.
 *
 * Adding happens in a row inside this dialog rather than in a second dialog
 * on top of it: every open Modal listens for Escape on `window` and traps
 * Tab on `document`, so two stacked ones would both close on one Escape.
 * For the same reason, while one of this dialog's confirmations is open the
 * dialog stops listening for Escape and ignores its own controls: Tab can
 * carry focus out of a confirmation (it has no trap of its own), and nothing
 * behind it may act on a draft the confirmation is still being asked about.
 */

type RowStatus = "kept" | "new" | "removed";

type Row = { ext: string; status: RowStatus };

type Props = {
  listKey: FileTypeListKey;
  /** The saved policy. Save sends its mode and the other list unchanged. */
  policy: FileTypePolicy;
  onClose: () => void;
  onSaved: (policy: FileTypePolicy, changes: { added: string[]; removed: string[] }) => void;
};

const COPY: Record<FileTypeListKey, { title: string; lead: ReactNode; empty: string }> = {
  blocked: {
    title: "Block list",
    lead: (
      <>
        An upload is refused when any extension in its name is on this list, in either mode —{" "}
        <code>report.pdf.exe</code> is refused for <code>exe</code>.
      </>
    ),
    empty: "The Block list is empty: no file is refused for its extension.",
  },
  allowed: {
    title: "Allow list",
    lead: (
      <>
        In “Allow only listed types” mode an upload is accepted only when its last extension is on this list, and
        never when any extension in its name is on the Block list.
      </>
    ),
    empty: "The Allow list is empty.",
  },
};

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

function sortedUnique(list: string[]): string[] {
  return [...new Set(list)].sort();
}

/** ".exe, .svg and 3 more" — enough to recognise the list without a wall of text. */
function listForHumans(exts: string[], max = 12): string {
  const shown = exts.slice(0, max).map((e) => `.${e}`);
  const rest = exts.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} and ${rest} more` : shown.join(", ");
}

export default function FileTypeListModal({ listKey, policy, onClose, onSaved }: Props) {
  const { confirm } = useConfirm();
  const { readOnly, writeLockProps } = useAdminWriteLock();
  const copy = COPY[listKey];
  const saved = policy[listKey];
  const defaults = listKey === "blocked" ? policy.default_blocked : policy.default_allowed;
  const inEffect = listKey === "blocked" || policy.mode === "allowlist";

  const [draft, setDraft] = useState<string[]>(() => sortedUnique(saved));
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addText, setAddText] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const busy = saving || confirming;
  const locked = readOnly || busy;
  const searchRef = useRef<HTMLInputElement>(null);
  const addInputRef = useRef<HTMLInputElement>(null);
  const addButtonRef = useRef<HTMLButtonElement>(null);
  // Where focus was when a confirmation opened; it goes back there after.
  const focusAfterConfirm = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (addOpen) addInputRef.current?.focus();
  }, [addOpen]);

  useEffect(() => {
    if (confirming) return;
    const el = focusAfterConfirm.current;
    focusAfterConfirm.current = null;
    if (!el || !document.contains(el)) return;
    if ((el as HTMLButtonElement).disabled) searchRef.current?.focus();
    else el.focus();
  }, [confirming]);

  const draftSet = useMemo(() => new Set(draft), [draft]);
  const blockedSet = useMemo(() => new Set(policy.blocked), [policy.blocked]);

  const rows = useMemo<Row[]>(() => {
    const savedSet = new Set(saved);
    return sortedUnique([...saved, ...draft]).map((ext) => ({
      ext,
      status: !savedSet.has(ext) ? "new" : draftSet.has(ext) ? "kept" : "removed",
    }));
  }, [saved, draft, draftSet]);

  const visibleRows = useMemo(() => {
    const shown = new Set(filterExtensions(rows.map((r) => r.ext), query));
    return rows.filter((r) => shown.has(r.ext));
  }, [rows, query]);

  const changes = useMemo(() => diffLists(saved, draft), [saved, draft]);
  const dirty = changes.added.length + changes.removed.length > 0;
  const matchesDefaults = useMemo(() => {
    const d = diffLists(sortedUnique(defaults), draft);
    return d.added.length + d.removed.length === 0;
  }, [defaults, draft]);
  const overCap = draft.length > MAX_LIST_ENTRIES;

  const q = normalizeSearchQuery(query);
  // Typing a type that is not there is usually the first step of adding it.
  const offerAdd = !readOnly && EXTENSION_PATTERN.test(q) && !rows.some((r) => r.ext === q);

  const addPreview = useMemo(() => {
    const { valid, invalid } = normalizeExtensionInput(addText);
    return {
      fresh: valid.filter((ext) => !draftSet.has(ext)),
      already: valid.filter((ext) => draftSet.has(ext)),
      invalid,
    };
  }, [addText, draftSet]);

  function addEntries(exts: string[]) {
    if (locked || !exts.length) return;
    setDraft((d) => sortedUnique([...d, ...exts]));
    setError("");
    setNotice(`Added ${listForHumans(exts)} — not saved yet.`);
  }

  function addFromSearch() {
    addEntries([q]);
    // The button that was clicked disappears once the type is listed.
    searchRef.current?.focus();
  }

  function remove(row: Row) {
    if (locked) return;
    setDraft((d) => d.filter((x) => x !== row.ext));
    setNotice("");
    // A new, unsaved entry leaves the list outright, and its × with it.
    if (row.status === "new") searchRef.current?.focus();
  }

  function undo(ext: string) {
    if (locked) return;
    setDraft((d) => sortedUnique([...d, ext]));
    setNotice("");
  }

  function resetToDefaults() {
    if (locked) return;
    setDraft(sortedUnique(defaults));
    setNotice("The list now matches the shipped defaults — not saved yet.");
  }

  function openAdd() {
    if (locked) return;
    setAddOpen(true);
    // Already open: the effect will not run again, so move focus here.
    addInputRef.current?.focus();
  }

  function closeAdd() {
    setAddOpen(false);
    setAddText("");
    addButtonRef.current?.focus();
  }

  function onAddSubmit(e: FormEvent) {
    e.preventDefault();
    if (locked || !addPreview.fresh.length) return;
    addEntries(addPreview.fresh);
    // Show the whole list again so the new rows are there to see.
    setQuery("");
    closeAdd();
  }

  function onAddPaste(e: ClipboardEvent<HTMLInputElement>) {
    // A one-line input drops the line breaks of a pasted column, which would
    // turn "psd⏎dwg" into one "psddwg". Keep them apart as commas instead.
    const text = e.clipboardData.getData("text");
    if (!/[\r\n]/.test(text)) return;
    e.preventDefault();
    const el = e.currentTarget;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const flat = text
      .split(/[\r\n]+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .join(", ");
    setAddText(el.value.slice(0, start) + flat + el.value.slice(end));
  }

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // The first Escape empties the search; only the next one closes the dialog.
    if (e.key === "Escape" && query) {
      e.stopPropagation();
      setQuery("");
    }
  }

  function onAddKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      closeAdd();
    }
  }

  async function ask(options: ConfirmOptions): Promise<boolean> {
    focusAfterConfirm.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirming(true);
    try {
      return (await confirm(options)) === true;
    } finally {
      setConfirming(false);
    }
  }

  async function requestClose() {
    if (busy) return;
    if (dirty && !readOnly) {
      const ok = await ask({
        title: "Discard your changes?",
        message: `Your changes to the ${copy.title} (+${changes.added.length} −${changes.removed.length}) have not been saved.`,
        confirmLabel: "Discard changes",
        cancelLabel: "Keep editing",
        danger: true,
      });
      if (!ok) return;
    }
    onClose();
  }

  async function save() {
    if (locked || !dirty || overCap) return;
    if (listKey === "blocked" && changes.removed.length) {
      const n = changes.removed.length;
      const allowOnly =
        policy.mode === "allowlist"
          ? " In “Allow only listed types” mode they are still accepted only if they are on the Allow list."
          : "";
      const ok = await ask({
        title: n === 1 ? "Unblock 1 file type?" : `Unblock ${n} file types?`,
        message:
          `The Block list will stop refusing ${listForHumans(changes.removed)}.${allowOnly} The fixed checks still ` +
          "apply: an executable is refused by its content under any name, and HTML or SVG is never opened in the " +
          "browser.",
        confirmLabel: "Unblock and save",
        cancelLabel: "Keep editing",
        danger: true,
      });
      if (!ok) return;
    }
    if (listKey === "allowed" && policy.mode === "allowlist" && draft.length === 0) {
      const ok = await ask({
        title: "Save an empty Allow list?",
        message:
          "The mode is “Allow only listed types”, so with nothing on the Allow list every upload will be refused.",
        emphasize: "every upload will be refused",
        emphasizeDanger: true,
        confirmLabel: "Save the empty list",
        cancelLabel: "Keep editing",
        danger: true,
      });
      if (!ok) return;
    }
    const body = {
      mode: policy.mode,
      blocked: listKey === "blocked" ? draft : policy.blocked,
      allowed: listKey === "allowed" ? draft : policy.allowed,
    };
    setSaving(true);
    setError("");
    try {
      const res = await api<{ ok?: boolean; file_types?: FileTypePolicy }>("/api/admin/storage/file-type-policy", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      onSaved(res?.file_types ?? { ...policy, ...body }, changes);
    } catch (err) {
      // Here, not behind the dialog: the draft is still on screen to fix.
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const customCount = draft.filter((ext) => !isDefaultType(ext, defaults)).length;
  let countLabel: string;
  if (!q) countLabel = `${plural(draft.length, "type", "types")}${customCount ? ` · ${customCount} custom` : ""}`;
  else if (visibleRows.length) countLabel = `${plural(visibleRows.length, "match", "matches")} for “${q}”`;
  else countLabel = `No matches for “${q}”`;

  const addShortcut = offerAdd ? (
    <button
      type="button"
      className="btn btn-ghost file-types-modal__shortcut"
      onClick={addFromSearch}
      disabled={busy}
    >
      Add .{q} to the {copy.title}
    </button>
  ) : null;

  let status: string;
  if (readOnly) status = "Read-only: you can search this list but not change it.";
  else if (saving) status = "Saving…";
  else if (dirty) status = `Unsaved: +${changes.added.length} −${changes.removed.length}`;
  else status = "No unsaved changes";

  return (
    <Modal
      open
      title={copy.title}
      onClose={() => void requestClose()}
      closeOnEscape={!confirming}
      panelClassName="modal-panel--md file-types-modal"
      bodyClassName="file-types-modal__body"
    >
      <p className="muted-text file-types-modal__lead">{copy.lead}</p>
      {!inEffect ? (
        <p className="alert alert-info file-types-modal__notice">
          Not in effect: the mode is “Block listed types”. You can still edit and save this list; it applies once the
          mode is switched to “Allow only listed types”.
        </p>
      ) : null}

      <div className="file-types-modal__toolbar">
        <input
          ref={searchRef}
          type="search"
          className="file-types-modal__search"
          placeholder="Search types"
          aria-label="Search file types"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setNotice("");
          }}
          onKeyDown={onSearchKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          ref={addButtonRef}
          type="button"
          className="btn file-types-modal__add"
          onClick={openAdd}
          disabled={locked}
          title={writeLockProps.title}
        >
          Add file type
        </button>
      </div>

      {addOpen ? (
        <form className="file-types-add-row" onSubmit={onAddSubmit} aria-label="Add file types">
          <label htmlFor="file-types-add-input" className="file-types-add-row__label">
            Extensions to add to the {copy.title}
          </label>
          <div className="file-types-add-row__controls">
            <input
              id="file-types-add-input"
              ref={addInputRef}
              className="file-types-add-row__input"
              value={addText}
              onChange={(e) => setAddText(e.target.value)}
              onKeyDown={onAddKeyDown}
              onPaste={onAddPaste}
              placeholder="psd, .dwg, parquet"
              autoComplete="off"
              spellCheck={false}
            />
            <button type="submit" className="btn" disabled={busy || !addPreview.fresh.length}>
              Add {plural(addPreview.fresh.length, "type", "types")}
            </button>
            <button type="button" className="btn btn-ghost btn-readonly-ok" onClick={closeAdd}>
              Cancel
            </button>
          </div>
          <p className="muted-text file-types-add-row__hint">
            Separate several with commas or spaces, or paste them one per line; the dot is optional. Letters and
            digits only, up to 16 characters — so <code>tar.gz</code> is entered as <code>gz</code>.
          </p>
          {addText.trim() ? (
            <ul className="file-types-add-preview" aria-label="Parsed file types">
              {addPreview.fresh.map((ext) => (
                <li key={`ok-${ext}`} className="file-types-add-preview__item is-ok">
                  <code>{ext}</code> <span aria-hidden="true">✓</span>
                  {listKey === "allowed" && blockedSet.has(ext) ? (
                    <span className="file-types-add-preview__note"> on the Block list, still refused</span>
                  ) : null}
                </li>
              ))}
              {addPreview.already.map((ext) => (
                <li key={`dup-${ext}`} className="file-types-add-preview__item is-listed muted-text">
                  <code>{ext}</code> already listed
                </li>
              ))}
              {addPreview.invalid.map((ext) => (
                <li key={`bad-${ext}`} className="file-types-add-preview__item is-invalid">
                  <code>{ext}</code> invalid
                </li>
              ))}
            </ul>
          ) : null}
        </form>
      ) : null}

      <div className="file-types-modal__meta">
        <span className="muted-text file-types-modal__count" aria-live="polite">
          {countLabel}
        </span>
        {/* Always mounted: a live region that appears with its text already
            in it is often not announced at all. */}
        <span className="file-types-modal__notice-line" role="status">
          {notice}
        </span>
      </div>

      {rows.length === 0 && !q ? (
        <p className="muted-text file-types-modal__empty">{copy.empty}</p>
      ) : visibleRows.length === 0 ? (
        <div className="file-types-modal__empty">
          {addShortcut ?? <p className="muted-text">Nothing on this list matches “{q}”.</p>}
        </div>
      ) : (
        <>
          {addShortcut}
          <ul className="file-types-rows" aria-label={copy.title}>
            {visibleRows.map((row) => (
              <li key={row.ext} className={`file-types-row is-${row.status}`}>
                <span className="file-types-row__name">.{row.ext}</span>
                {/* The shipped defaults are most of every list, so it is the
                    exceptions that are tagged: what an administrator added. */}
                {row.status !== "new" && !isDefaultType(row.ext, defaults) ? (
                  <span className="file-types-tag">custom</span>
                ) : null}
                {row.status === "new" ? <span className="file-types-tag is-new">new</span> : null}
                {row.status === "removed" ? <span className="file-types-tag is-removed">removed</span> : null}
                {listKey === "allowed" && row.status !== "removed" && blockedSet.has(row.ext) ? (
                  <span className="file-types-tag is-blocked" title="Also on the Block list, which wins: still refused">
                    still blocked
                  </span>
                ) : null}
                {row.status === "removed" ? (
                  <button
                    type="button"
                    className="btn-link file-types-row__undo"
                    aria-label={`Undo removing .${row.ext}`}
                    onClick={() => undo(row.ext)}
                    disabled={locked}
                  >
                    Undo
                  </button>
                ) : (
                  <button
                    type="button"
                    className="file-types-row__remove"
                    aria-label={`Remove .${row.ext}`}
                    onClick={() => remove(row)}
                    disabled={locked}
                    title={writeLockProps.title ?? `Remove .${row.ext}`}
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {overCap ? (
        <p className="alert alert-error file-types-modal__cap" role="alert">
          A list may hold at most {MAX_LIST_ENTRIES} types; this one has {draft.length}. Remove some before saving.
        </p>
      ) : null}
      {error ? (
        <p className="alert alert-error file-types-modal__error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="file-types-modal__footer">
        <button
          type="button"
          className="btn btn-ghost file-types-modal__reset"
          onClick={resetToDefaults}
          disabled={locked || matchesDefaults}
          title={writeLockProps.title}
        >
          Reset this list to defaults
        </button>
        <span className="muted-text file-types-modal__status">{status}</span>
        <div className="file-types-modal__actions">
          <button
            type="button"
            className="btn btn-ghost btn-readonly-ok"
            onClick={() => void requestClose()}
            disabled={saving}
          >
            {readOnly ? "Close" : "Cancel"}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => void save()}
            disabled={locked || !dirty || overCap}
            title={writeLockProps.title}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
