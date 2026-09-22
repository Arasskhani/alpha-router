import AuthenticatedAudio from "../AuthenticatedAudio";
import AuthenticatedImage from "../AuthenticatedImage";
import AuthenticatedVideo from "../AuthenticatedVideo";
import { downloadAuthenticatedMedia } from "../MarkdownContent";
import { formatFileSize } from "../../lib/attachmentPolicy";
import {
  attachmentDisplayText,
  type AttachmentMessagePayload,
  type ProcessedAttachment,
} from "../../lib/chatAttachments";
import { isAlphaRouterMediaFileUrl } from "../../lib/mediaUrl";

type Props = {
  payload: AttachmentMessagePayload;
  onOpenImage?: (url: string) => void;
};

/** Paperclip for attachments the platform has no parser or player for. */
function FileChipIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

/** Documents and files alike offer the stored bytes as a download when the server kept them. */
function AttachmentDownloadLink({ attachment }: { attachment: ProcessedAttachment }) {
  const url = (attachment.url || "").trim();
  if (!url || url.startsWith("data:")) return null;
  const authenticated = isAlphaRouterMediaFileUrl(url);
  return (
    <a
      className="alpha-router-attach-msg__download"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      download={attachment.name || undefined}
      onClick={(event) => {
        if (!authenticated) return;
        event.preventDefault();
        void downloadAuthenticatedMedia(url, attachment.name).catch((error) => {
          console.error("Attachment download failed", error);
        });
      }}
    >
      Download
    </a>
  );
}

export default function ChatAttachmentMessage({ payload, onOpenImage }: Props) {
  const images = payload.attachments.filter((a) => a.kind === "image");
  const videos = payload.attachments.filter((a) => a.kind === "video");
  const audios = payload.attachments.filter((a) => a.kind === "audio");
  const documents = payload.attachments.filter((a) => a.kind === "document");
  const files = payload.attachments.filter((a) => a.kind === "file");

  return (
    <div className="alpha-router-attach-msg">
      {payload.userText.trim() ? <p className="alpha-router-attach-msg__text">{payload.userText.trim()}</p> : null}
      {images.length > 0 ? (
        <div className="alpha-router-attach-msg__images">
          {images.map((img) => {
            const url = (img.url || img.data_url || "").trim();
            return (
              <figure key={url || img.name} className="alpha-router-attach-msg__image">
                {onOpenImage && url ? (
                  <button
                    type="button"
                    className="alpha-router-media-open"
                    onClick={() => onOpenImage(url)}
                    aria-label={`Open ${img.name || "image"}`}
                  >
                    <AuthenticatedImage url={url} alt={img.name} className="alpha-router-attach-msg__thumb" />
                  </button>
                ) : (
                  <AuthenticatedImage url={url} alt={img.name} className="alpha-router-attach-msg__thumb" />
                )}
                <figcaption>{img.name}</figcaption>
              </figure>
            );
          })}
        </div>
      ) : null}
      {videos.length > 0 ? (
        <div className="alpha-router-attach-msg__videos">
          {videos.map((clip) => {
            const url = (clip.url || clip.data_url || "").trim();
            return (
              <figure key={url || clip.name} className="alpha-router-attach-msg__video">
                {url ? (
                  <AuthenticatedVideo
                    url={url}
                    title={clip.name}
                    className="alpha-router-generated-video alpha-router-attach-msg__video-el"
                  />
                ) : null}
                <figcaption>{clip.name}</figcaption>
              </figure>
            );
          })}
        </div>
      ) : null}
      {audios.length > 0 ? (
        <ul className="alpha-router-attach-msg__audios">
          {audios.map((track) => {
            const url = (track.url || track.data_url || "").trim();
            return (
              <li key={url || track.name}>
                {url ? <AuthenticatedAudio url={url} title={track.name} /> : null}
                <span className="alpha-router-attach-msg__doc-name">{track.name}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {documents.length > 0 || files.length > 0 ? (
        <ul className="alpha-router-attach-msg__docs">
          {documents.map((doc) => (
            <li key={doc.url || doc.name}>
              <span className="alpha-router-attach-msg__doc-icon" aria-hidden>
                📄
              </span>
              <span className="alpha-router-attach-msg__doc-name">{doc.name}</span>
              <AttachmentDownloadLink attachment={doc} />
            </li>
          ))}
          {files.map((file) => (
            <li key={file.url || file.name} className="chat-attachment-file">
              <span className="alpha-router-attach-msg__doc-icon chat-attachment-file__icon" aria-hidden>
                <FileChipIcon />
              </span>
              <span className="alpha-router-attach-msg__doc-name">{file.name}</span>
              {typeof file.size_bytes === "number" ? (
                <span className="chat-attachment-file__meta">{formatFileSize(file.size_bytes)}</span>
              ) : null}
              {file.binary || file.text === null ? (
                <span className="chat-attachment-file__meta">no preview</span>
              ) : null}
              <AttachmentDownloadLink attachment={file} />
            </li>
          ))}
        </ul>
      ) : null}
      {!payload.userText.trim() &&
      !images.length &&
      !videos.length &&
      !audios.length &&
      !documents.length &&
      !files.length ? (
        <p>{attachmentDisplayText(payload)}</p>
      ) : null}
    </div>
  );
}
