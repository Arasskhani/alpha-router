import { useEffect } from "react";
import AuthenticatedImage from "./AuthenticatedImage";
import AuthenticatedVideo from "./AuthenticatedVideo";
import Modal from "./Modal";
import { ChevronLeftIcon, ChevronRightIcon, OpenFullSizeIcon } from "./chat/GeneratedImageIcons";
import type { MediaViewerItem } from "../lib/mediaViewer";

type Props = {
  items: MediaViewerItem[];
  index: number | null;
  onClose: () => void;
  onIndexChange: (index: number) => void;
  onOpenExternal?: (item: MediaViewerItem) => void;
};

export default function MediaViewerModal({
  items,
  index,
  onClose,
  onIndexChange,
  onOpenExternal,
}: Props) {
  const currentIndex = index != null && index >= 0 && index < items.length ? index : null;
  const open = currentIndex != null;
  const current = open ? items[currentIndex] : null;
  const showNav = items.length > 1;
  const canPrev = currentIndex != null && currentIndex > 0;
  const canNext = currentIndex != null && currentIndex < items.length - 1;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" && canPrev) {
        event.preventDefault();
        onIndexChange(currentIndex - 1);
      } else if (event.key === "ArrowRight" && canNext) {
        event.preventDefault();
        onIndexChange(currentIndex + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, currentIndex, canPrev, canNext, onIndexChange]);

  return (
    <Modal
      open={open}
      title={current?.title || current?.alt || "Media"}
      onClose={onClose}
      compactHeader
      panelClassName="modal-panel--media-viewer"
      bodyClassName="media-viewer-body"
      headerActions={
        current && onOpenExternal ? (
          <button
            type="button"
            className="media-viewer__external"
            title="Open in new tab"
            aria-label="Open in new tab"
            onClick={() => onOpenExternal(current)}
          >
            <OpenFullSizeIcon />
          </button>
        ) : null
      }
    >
      {current ? (
        <div className="media-viewer">
          {showNav ? (
            <button
              type="button"
              className="media-viewer__nav media-viewer__nav--prev"
              aria-label="Previous"
              disabled={!canPrev}
              onClick={() => canPrev && currentIndex != null && onIndexChange(currentIndex - 1)}
            >
              <ChevronLeftIcon />
            </button>
          ) : (
            <span className="media-viewer__nav-spacer media-viewer__nav-spacer--prev" aria-hidden />
          )}
          <div className="media-viewer__stage">
            {current.kind === "video" ? (
              <AuthenticatedVideo
                key={current.id}
                url={current.url}
                className="media-viewer__media"
                title={current.title || current.alt || "Video"}
              />
            ) : (
              <AuthenticatedImage
                key={current.id}
                url={current.url}
                alt={current.alt || "Image"}
                className="media-viewer__media"
              />
            )}
          </div>
          {showNav ? (
            <button
              type="button"
              className="media-viewer__nav media-viewer__nav--next"
              aria-label="Next"
              disabled={!canNext}
              onClick={() => canNext && currentIndex != null && onIndexChange(currentIndex + 1)}
            >
              <ChevronRightIcon />
            </button>
          ) : (
            <span className="media-viewer__nav-spacer media-viewer__nav-spacer--next" aria-hidden />
          )}
          <p className="media-viewer__meta">
            {showNav ? (
              <span>
                {currentIndex != null ? currentIndex + 1 : 0} / {items.length}
              </span>
            ) : null}
            {current.title ? <span className="media-viewer__caption">{current.title}</span> : null}
          </p>
        </div>
      ) : null}
    </Modal>
  );
}
