import { PRODUCT_NAME, PRODUCT_NAME_MARKED, TRADEMARK_SYMBOL } from "../lib/brand";

type Props = {
  size?: number;
  className?: string;
  /**
   * Use the brand mark as the leading “A” of Alpha
   * (mark + “lpha …”), matching wordmark ink.
   */
  showMark?: boolean;
  /** Split into animated parts (login assemble). */
  splitWords?: boolean;
  /**
   * Login lockup: one glued word “Alpharouter” —
   * large mark-A + lowercase rest, no space.
   */
  joined?: boolean;
  /** Show ™ after the wordmark. Default on — this component is the brand lockup. */
  showTrademark?: boolean;
};

function TrademarkSign() {
  return (
    <span className="alpha-router-logo-tm" aria-hidden>
      {TRADEMARK_SYMBOL}
    </span>
  );
}

const MARK_URL = "/alpha-router-mark.png?v=7";
const MARK_URL_HARD = "/alpha-router-mark-hard.png?v=7";

/** Wordmark: optional mark-as-A + remaining letters. */
export default function AlphaRouterLogo({
  size = 32,
  className = "",
  showMark = false,
  splitWords = false,
  joined = false,
  showTrademark = true,
}: Props) {
  const wordSize = Math.round(size * 0.86);
  /* Joined login: mark reads as display cap above lowercase. */
  const markSize = Math.max(
    12,
    Math.round(wordSize * (joined ? 1.216 : 0.874)),
  );
  const [, ...rest] = PRODUCT_NAME.split(/\s+/);
  const routerWord = rest.join(" ") || "Router";
  const routerText = joined ? routerWord.toLowerCase() : routerWord;
  const alphaRest = showMark ? "lpha" : null;
  /* Joined assemble: full lowercase rest after the mark. */
  const joinedRest = `lpha${routerText}`;

  const markUrl = className.includes("topbar") ? MARK_URL_HARD : MARK_URL;
  const mark = showMark ? (
    <span
      className="alpha-router-logo-mark"
      aria-hidden
      style={
        joined
          ? { ["--alpha-mark-url" as string]: `url(${markUrl})` }
          : {
              width: markSize,
              height: markSize,
              ["--alpha-mark-url" as string]: `url(${markUrl})`,
            }
      }
    />
  ) : null;

  const wordClass = [
    "alpha-router-logo-word",
    showMark ? "alpha-router-logo-word--mark-as-a" : "",
    joined ? "alpha-router-logo-word--joined" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      className={wordClass}
      aria-label={showTrademark ? PRODUCT_NAME_MARKED : PRODUCT_NAME}
      style={{ fontSize: `${wordSize}px`, lineHeight: `${size}px` }}
    >
      {joined && showMark && splitWords ? (
        /* Login: A first, then “lpharouter” drops in from above */
        <span className="alpha-router-logo-tail alpha-router-logo-tail--split">
          <span className="alpha-router-logo-part alpha-router-logo-part--mark">{mark}</span>
          <span className="alpha-router-logo-part alpha-router-logo-part--rest">{joinedRest}</span>
        </span>
      ) : splitWords ? (
        <span className="alpha-router-logo-tail alpha-router-logo-tail--split">
          <span className="alpha-router-logo-part alpha-router-logo-part--alpha">
            {showMark ? (
              <span className="alpha-router-logo-alpha">
                {mark}
                <span className="alpha-router-logo-alpha-rest">{alphaRest}</span>
              </span>
            ) : (
              <span className="alpha-router-logo-alpha">Alpha</span>
            )}
          </span>
          <span className="alpha-router-logo-part alpha-router-logo-part--gap" aria-hidden>
            {"\u00A0"}
          </span>
          <span className="alpha-router-logo-part alpha-router-logo-part--router">{routerText}</span>
        </span>
      ) : (
        <span className="alpha-router-logo-tail">
          {showMark ? (
            <span className="alpha-router-logo-alpha">
              {mark}
              <span className="alpha-router-logo-alpha-rest">{alphaRest}</span>
            </span>
          ) : (
            <span className="alpha-router-logo-alpha">{joined ? "alpha" : "Alpha"}</span>
          )}
          {joined ? null : "\u00A0"}
          {routerText}
        </span>
      )}
      {showTrademark ? <TrademarkSign /> : null}
    </span>
  );
}
