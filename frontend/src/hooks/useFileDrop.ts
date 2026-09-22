import { useCallback, useRef, useState, type DragEvent } from "react";

/**
 * Drag-and-drop of files onto a large target, with the browser's quirks kept
 * out of the component that uses it.
 *
 * Two of those quirks decide the shape of this hook. `dragleave` fires every
 * time the pointer crosses into a child element, so a boolean "is something
 * over us" flickers off and on across a page full of children; a depth
 * counter of enters minus leaves does not. And a drag of text, a link, or one
 * of our own sidebar chats also carries a `dataTransfer`, so the hook reacts
 * only when the drag carries `Files` — everything else is left alone for the
 * handlers that own it.
 */

export const DROP_DIRECTORY_MESSAGE = "Folders cannot be attached. Drop the files themselves.";
export const DROP_BUSY_MESSAGE = "Wait for the current reply to finish before attaching files.";

export function dropOverflowMessage(kept: number, dropped: number): string {
  if (kept === 0) return "No more files can be attached to this message. Remove one first.";
  return `Only ${kept} more file${kept === 1 ? "" : "s"} could be attached; ${dropped} ${dropped === 1 ? "was" : "were"} left out.`;
}

/** True when the drag carries files (not text, a link or an app-internal item). */
export function dragCarriesFiles(dt: DataTransfer | null | undefined): boolean {
  if (!dt) return false;
  const types = Array.from(dt.types || []);
  return types.includes("Files");
}

export type DroppedPayload = {
  files: File[];
  /** At least one dropped item was a folder, which the browser cannot hand over as files. */
  hadDirectory: boolean;
};

/**
 * The files in a drop. Folders are reported rather than silently yielding an
 * empty `File` with the folder's name, which is what `dt.files` would give.
 */
export function filesFromDrop(dt: DataTransfer | null | undefined): DroppedPayload {
  if (!dt) return { files: [], hadDirectory: false };
  const items = dt.items ? Array.from(dt.items) : [];
  let hadDirectory = false;
  const files: File[] = [];
  if (items.length) {
    for (const item of items) {
      if (item.kind !== "file") continue;
      // Non-standard but universal in the browsers this product supports;
      // guarded because test DOMs and older engines lack it.
      const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => { isDirectory: boolean } | null })
        .webkitGetAsEntry?.();
      if (entry?.isDirectory) {
        hadDirectory = true;
        continue;
      }
      const file = item.getAsFile();
      if (file) files.push(file);
    }
    return { files, hadDirectory };
  }
  return { files: Array.from(dt.files || []), hadDirectory: false };
}

export type UseFileDropOptions = {
  /** When false, drags are ignored entirely (read-only account, no session). */
  enabled: boolean;
  /**
   * Asked at drop time; when it answers true the drop is refused with
   * `DROP_BUSY_MESSAGE`. A function rather than a flag because the caller
   * knows "a reply is streaming" from refs it must not read during render.
   */
  isBusy?: () => boolean;
  /** How many more files the message can take right now. */
  remainingSlots: number;
  onFiles: (files: File[]) => void;
  onReject: (message: string) => void;
};

export type FileDropHandlers = {
  onDragEnter: (e: DragEvent) => void;
  onDragOver: (e: DragEvent) => void;
  onDragLeave: (e: DragEvent) => void;
  onDrop: (e: DragEvent) => void;
};

export function useFileDrop(opts: UseFileDropOptions): { active: boolean; handlers: FileDropHandlers } {
  const [active, setActive] = useState(false);
  const depth = useRef(0);
  const { enabled, isBusy, remainingSlots, onFiles, onReject } = opts;

  const reset = useCallback(() => {
    depth.current = 0;
    setActive(false);
  }, []);

  const onDragEnter = useCallback(
    (e: DragEvent) => {
      if (!enabled || !dragCarriesFiles(e.dataTransfer)) return;
      e.preventDefault();
      depth.current += 1;
      if (depth.current === 1) setActive(true);
    },
    [enabled],
  );

  const onDragOver = useCallback(
    (e: DragEvent) => {
      if (!enabled || !dragCarriesFiles(e.dataTransfer)) return;
      // Without this the browser navigates to the dropped file.
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = isBusy?.() ? "none" : "copy";
    },
    [enabled, isBusy],
  );

  const onDragLeave = useCallback(
    (e: DragEvent) => {
      if (!enabled || !dragCarriesFiles(e.dataTransfer)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    },
    [enabled],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      if (!enabled || !dragCarriesFiles(e.dataTransfer)) return;
      e.preventDefault();
      reset();
      if (isBusy?.()) {
        onReject(DROP_BUSY_MESSAGE);
        return;
      }
      const { files, hadDirectory } = filesFromDrop(e.dataTransfer);
      if (hadDirectory) onReject(DROP_DIRECTORY_MESSAGE);
      if (!files.length) return;
      const slots = Math.max(0, remainingSlots);
      const kept = files.slice(0, slots);
      if (kept.length < files.length) onReject(dropOverflowMessage(kept.length, files.length - kept.length));
      if (kept.length) onFiles(kept);
    },
    [enabled, isBusy, remainingSlots, onFiles, onReject, reset],
  );

  return { active, handlers: { onDragEnter, onDragOver, onDragLeave, onDrop } };
}
