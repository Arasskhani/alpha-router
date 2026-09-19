import { useAuthenticatedMediaSource } from "../hooks/useAuthenticatedMediaSource";

type Props = {
  url: string;
  className?: string;
  title?: string;
  controls?: boolean;
};

export default function AuthenticatedVideo({ url, className, title, controls = true }: Props) {
  const { src, failed } = useAuthenticatedMediaSource(url, "media");

  if (failed) {
    return <div className="alpha-router-generated-video alpha-router-generated-video--error">Video unavailable</div>;
  }
  if (!src) {
    return <div className="alpha-router-generated-video alpha-router-generated-video--loading">Loading video…</div>;
  }
  return (
    <video
      src={src}
      className={className}
      title={title || "Generated video"}
      controls={controls}
      playsInline
      preload="metadata"
    />
  );
}
