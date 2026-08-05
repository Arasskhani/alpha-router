import { PRODUCT_NAME } from "../lib/brand";

type Props = {
  size?: number;
  className?: string;
  /** Show the wolf mark to the left of the wordmark (topbar). */
  showMark?: boolean;
};

/** Inline wordmark with the optional Alpha Router SVG mark. */
export default function AlphaRouterLogo({ size = 32, className = "", showMark = false }: Props) {
  const wordSize = Math.round(size * 0.86);
  /* Intrinsic attrs; topbar CSS overrides to ~28px inside the fixed 40px bar. */
  const markSize = Math.max(16, Math.round(size * 1.25));
  return (
    <span
      className={`alpha-router-logo-word${showMark ? " alpha-router-logo-word--with-mark" : ""} ${className}`.trim()}
      aria-label={PRODUCT_NAME}
      style={{ fontSize: `${wordSize}px`, lineHeight: `${size}px` }}
    >
      {showMark ? (
        <img
          className="alpha-router-logo-mark"
          src="/alpha-router-mark.svg"
          alt=""
          width={markSize}
          height={markSize}
          draggable={false}
        />
      ) : null}
      <span className="alpha-router-logo-tail">{PRODUCT_NAME}</span>
    </span>
  );
}
