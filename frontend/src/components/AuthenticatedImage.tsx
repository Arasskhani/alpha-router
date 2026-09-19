import { useAuthenticatedMediaSource } from "../hooks/useAuthenticatedMediaSource";

type Props = {
  url: string;
  alt: string;
  className?: string;
};

export default function AuthenticatedImage({ url, alt, className }: Props) {
  const { src, failed } = useAuthenticatedMediaSource(url, "image");

  if (failed) {
    return <div className="alpha-router-generated-image alpha-router-generated-image--error">Image unavailable</div>;
  }
  if (!src) {
    return <div className="alpha-router-generated-image alpha-router-generated-image--loading">Loading image…</div>;
  }
  return <img src={src} alt={alt} className={className} />;
}
