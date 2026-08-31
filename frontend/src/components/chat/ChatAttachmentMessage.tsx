import AuthenticatedImage from "../AuthenticatedImage";
import {
  attachmentDisplayText,
  type AttachmentMessagePayload,
} from "../../lib/chatAttachments";

type Props = {
  payload: AttachmentMessagePayload;
  onOpenImage?: (url: string) => void;
};

export default function ChatAttachmentMessage({ payload, onOpenImage }: Props) {
  const images = payload.attachments.filter((a) => a.kind === "image");
  const documents = payload.attachments.filter((a) => a.kind === "document");

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
      {documents.length > 0 ? (
        <ul className="alpha-router-attach-msg__docs">
          {documents.map((doc) => (
            <li key={doc.url}>
              <span className="alpha-router-attach-msg__doc-icon" aria-hidden>
                📄
              </span>
              <span className="alpha-router-attach-msg__doc-name">{doc.name}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {!payload.userText.trim() && !images.length && !documents.length ? (
        <p>{attachmentDisplayText(payload)}</p>
      ) : null}
    </div>
  );
}
