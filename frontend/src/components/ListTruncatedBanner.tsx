import type { ListBounds } from "../api";

/**
 * Says that the server did not return every matching row.
 *
 * These admin lists are capped rather than paged, because an operator looking
 * for somebody filters rather than scrolls. A cap with no notice would be
 * worse than no cap at all: a page silently showing 2000 of 50000 accounts
 * tells the operator the other 48000 are gone.
 */
export default function ListTruncatedBanner({
  bounds,
  noun = "rows",
  className = "",
}: {
  bounds: ListBounds;
  noun?: string;
  className?: string;
}) {
  if (!bounds.truncated) return null;
  return (
    <div className={`alert alert-warning${className ? ` ${className}` : ""}`} role="status">
      {`Showing the first ${bounds.cap.toLocaleString()} ${noun}. There are more — narrow the search or the filters to find what you are looking for.`}
    </div>
  );
}
