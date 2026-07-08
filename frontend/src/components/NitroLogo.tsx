import { PRODUCT_NAME } from "../lib/brand";

type Props = {
  size?: number;
  className?: string;
};

/** Inline wordmark (not a raster image). */
export default function NitroLogo({ size = 32, className = "" }: Props) {
  const wordSize = Math.round(size * 0.86);
  return (
    <span
      className={`nitro-logo-word ${className}`.trim()}
      aria-label={PRODUCT_NAME}
      style={{ fontSize: `${wordSize}px`, lineHeight: `${size}px` }}
    >
      <span className="nitro-logo-tail">{PRODUCT_NAME}</span>
    </span>
  );
}
