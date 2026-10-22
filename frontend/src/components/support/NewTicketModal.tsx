import { useId, useRef, useState, type DragEvent, type FormEvent } from "react";
import Modal from "../Modal";
import { useConfirm } from "../../context/ConfirmContext";
import {
  PRIORITY_LABELS,
  SUPPORT_BASE,
  TicketsApiError,
  ticketsRequest,
  type Priority,
  type SupportStatus,
  type TicketContext,
  type UserTicketDetail,
} from "../../lib/tickets";
import { Avatar, ImageThumbs } from "./SupportBits";
import { pageBeforeSupport } from "./lastPage";
import { imageExtensions, imageTypesLabel, isTicketsDisabled, plural, supportErrorText } from "./supportFormat";
import { useImagePicks } from "./useImagePicks";

const TITLE_MAX = 150;
export const BODY_MAX = 5000;
const CONTEXT_MAX = 200;

type Props = {
  status: SupportStatus;
  onClose: () => void;
  onCreated: (ticket: UserTicketDetail) => void;
  onDisabled: () => void;
  /** The category list changed under the form (invalid_category): read /status again. */
  onStale: () => void;
};

function technicalDetails(): TicketContext {
  return {
    browser: navigator.userAgent.slice(0, CONTEXT_MAX),
    page: pageBeforeSupport().slice(0, CONTEXT_MAX),
  };
}

/** The image picker's input `accept`: ".png,.jpg,.jpeg,…". */
export function acceptAttribute(types: string[]): string {
  return imageExtensions(types)
    .map((t) => `.${t}`)
    .join(",");
}

/** + New ticket: reporter, title, category, priority, description, screenshots, technical details. */
export default function NewTicketModal({ status, onClose, onCreated, onDisabled, onStale }: Props) {
  const ids = useId();
  const confirmer = useConfirm();
  const { limits, reporter } = status;
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(status.categories[0] ?? "");
  const [priority, setPriority] = useState<Priority>("normal");
  const [withContext, setWithContext] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const images = useImagePicks(limits);

  // The list may change under an open dialog (invalid_category, then /status again).
  const categoryShown = status.categories.includes(category) ? category : (status.categories[0] ?? "");
  const priorities = status.priorities?.length ? status.priorities : (Object.keys(PRIORITY_LABELS) as Priority[]);
  const ready = title.trim() !== "" && description.trim() !== "" && categoryShown !== "" && !busy;
  const hasDraft = title.trim() !== "" || description.trim() !== "" || images.picks.length > 0;

  /** Escape, × and Cancel: never while sending, and only after asking when something was written. */
  const requestClose = async () => {
    if (busy) return;
    if (hasDraft) {
      const ok = await confirmer.confirm({
        title: "Discard this ticket?",
        message: "What you wrote and the images you added will not be sent.",
        confirmLabel: "Discard",
        cancelLabel: "Keep editing",
        danger: true,
      });
      if (ok !== true) return;
    }
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("title", title.trim());
    form.append("description", description.trim());
    form.append("category", categoryShown);
    form.append("priority", priority);
    if (withContext) form.append("context", JSON.stringify(technicalDetails()));
    for (const pick of images.picks) form.append("images", pick.file, pick.file.name);
    try {
      const ticket = await ticketsRequest<UserTicketDetail>(`${SUPPORT_BASE}/tickets`, { method: "POST", body: form });
      images.clear();
      onCreated(ticket);
    } catch (err) {
      setBusy(false);
      if (isTicketsDisabled(err)) {
        onDisabled();
        return;
      }
      if (err instanceof TicketsApiError &&
      (err.code === "image_rejected" || err.code === "image_too_large") &&
      typeof err.data.file === "string") {
        images.refuse(err.data.file, "refused");
      }
      if (err instanceof TicketsApiError && err.code === "invalid_category") onStale();
      setError(supportErrorText(err, limits));
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    images.add(event.dataTransfer?.files);
  };

  return (
    <Modal
      open
      title="New ticket"
      onClose={() => void requestClose()}
      closeOnBackdrop={false}
      panelClassName="support-modal"
    >
      <form className="support-form" onSubmit={(e) => void submit(e)} noValidate>
        <div className="support-reporter">
          <Avatar name={reporter.name || reporter.username} />
          <span>
            Sent as <b>{reporter.name || reporter.username}</b>
            {reporter.email ? ` · ${reporter.email}` : ""}
            {reporter.department ? ` · ${reporter.department}` : ""}
          </span>
        </div>

        <div className="support-field">
          <div className="support-field__head">
            <label htmlFor={`${ids}-title`}>
              Title <span className="support-req" aria-hidden="true">*</span>
            </label>
            <span className="support-counter" aria-hidden="true">
              {title.length} / {TITLE_MAX}
            </span>
          </div>
          <input
            id={`${ids}-title`}
            className="input-block"
            value={title}
            maxLength={TITLE_MAX}
            required
            dir="auto"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div className="support-row2">
          <div className="support-field">
            <label htmlFor={`${ids}-category`}>Category</label>
            <select
              id={`${ids}-category`}
              className="input-block"
              value={categoryShown}
              onChange={(e) => setCategory(e.target.value)}
            >
              {status.categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="support-field">
            <span className="support-field__label" id={`${ids}-priority`}>
              Priority
            </span>
            <div className="support-prio" role="group" aria-labelledby={`${ids}-priority`}>
              {priorities.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`support-prio__btn support-prio__btn--${p}${priority === p ? " is-on" : ""}`}
                  aria-pressed={priority === p}
                  onClick={() => setPriority(p)}
                >
                  {PRIORITY_LABELS[p] ?? p}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="support-field">
          <div className="support-field__head">
            <label htmlFor={`${ids}-description`}>
              Description <span className="support-req" aria-hidden="true">*</span>
            </label>
            <span className="support-counter" aria-hidden="true">
              {description.length} / {BODY_MAX}
            </span>
          </div>
          <textarea
            id={`${ids}-description`}
            className="input-block"
            rows={5}
            value={description}
            maxLength={BODY_MAX}
            required
            dir="auto"
            placeholder="What happened, what you expected, and the steps to see it again."
            onChange={(e) => setDescription(e.target.value)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData?.files ?? []);
              if (files.length > 0) {
                e.preventDefault();
                images.add(files);
              }
            }}
          />
        </div>

        <div className="support-field">
          <span className="support-field__label">Screenshots</span>
          <div
            className={`support-drop${dragging ? " is-dragging" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <p className="support-drop__cta">
              <span aria-hidden="true">⬆</span> Drop images here or{" "}
              <button type="button" className="support-linkbtn" onClick={() => fileRef.current?.click()}>
                browse
              </button>{" "}
              · {imageTypesLabel(limits.image_types)} · up to {limits.max_image_mb} MB each · up to{" "}
              {plural(limits.max_images, "image")}
            </p>
            <input
              ref={fileRef}
              type="file"
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              accept={acceptAttribute(limits.image_types)}
              multiple
              data-testid="support-new-files"
              onChange={(e) => {
                images.add(e.target.files);
                e.target.value = "";
              }}
            />
            <ImageThumbs
              picks={images.picks}
              refused={images.refused}
              onRemove={images.remove}
              onDismiss={images.dismiss}
            />
            <p className="support-hint">
              Only images are accepted. Each one is checked and saved again as a clean copy, without its location or
              camera data.
            </p>
          </div>
        </div>

        <label className="support-check">
          <input type="checkbox" checked={withContext} onChange={(e) => setWithContext(e.target.checked)} />
          <span>Include technical details: browser and the page I was on</span>
        </label>

        {error ? (
          <p className="alert alert-error support-form__error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="modal-actions support-actions">
          <button type="button" className="btn btn-ghost" onClick={() => void requestClose()} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn" disabled={!ready}>
            {busy ? "Sending…" : "Submit ticket"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
