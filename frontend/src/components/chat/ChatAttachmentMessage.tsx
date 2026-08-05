import AuthenticatedImage from "../AuthenticatedImage";
import {
  attachmentDisplayText,
  type AttachmentMessagePayload,
} from "../../lib/chatAttachments";

type Props = {
  payload: AttachmentMessagePayload;
};

export default function ChatAttachmentMessage({ payload }: Props) {
  const images = payload.attachments.filter((a) => a.kind === "image");
  const documents = payload.attachments.filter((a) => a.kind === "document");

  return (
    <div className="alpha-router-attach-msg">
      {payload.userText.trim() ? <p className="alpha-router-attach-msg__text">{payload.userText.trim()}</p> : null}
      {images.length > 0 ? (
        <div className="alpha-router-attach-msg__images">
          {images.map((img) => (
            <figure key={img.url} className="alpha-router-attach-msg__image">
              <AuthenticatedImage url={img.url} alt={img.name} className="alpha-router-attach-msg__thumb" />
              <figcaption>{img.name}</figcaption>
            </figure>
          ))}
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
