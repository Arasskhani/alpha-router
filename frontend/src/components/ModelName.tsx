import ModelProviderIcon from "./ModelProviderIcon";

type Props = {
  /** Prefer full model id for accurate provider detection. */
  modelId?: string | null;
  /** Display text (falls back to modelId). */
  label?: string | null;
  /** Explicit provider override when known. */
  provider?: string | null;
  size?: number;
  className?: string;
  /** When false, skip icon (e.g. non-model entity rows). */
  showIcon?: boolean;
};

/**
 * Model label with a colored provider brand mark on the left.
 */
export default function ModelName({
  modelId,
  label,
  provider,
  size = 16,
  className = "",
  showIcon = true,
}: Props) {
  const text = (label || modelId || "").trim() || "—";
  return (
    <span className={`model-name${className ? ` ${className}` : ""}`}>
      {showIcon ? (
        <ModelProviderIcon modelId={modelId || label} provider={provider} size={size} />
      ) : null}
      <span className="model-name__text">{text}</span>
    </span>
  );
}
