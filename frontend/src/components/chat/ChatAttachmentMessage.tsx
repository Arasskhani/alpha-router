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
    <div className="cgpt-attach-msg">
      {payload.userText.trim() ? <p className="cgpt-attach-msg__text">{payload.userText.trim()}</p> : null}
      {images.length > 0 ? (
        <div className="cgpt-attach-msg__images">
          {images.map((img) => (
            <figure key={img.url} className="cgpt-attach-msg__image">
              <AuthenticatedImage url={img.url} alt={img.name} className="cgpt-attach-msg__thumb" />
              <figcaption>{img.name}</figcaption>
            </figure>
          ))}
        </div>
      ) : null}
      {documents.length > 0 ? (
        <ul className="cgpt-attach-msg__docs">
          {documents.map((doc) => (
            <li key={doc.url}>
              <span className="cgpt-attach-msg__doc-icon" aria-hidden>
                📄
              </span>
              <span className="cgpt-attach-msg__doc-name">{doc.name}</span>
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
