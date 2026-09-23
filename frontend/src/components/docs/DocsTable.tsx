import type { ReactNode } from "react";

/**
 * A table in the User Manual or the Admin Guide. The wrapper scrolls it
 * sideways when it is wider than the text, as on a phone, instead of the
 * table running off the edge of the screen.
 */
export default function DocsTable({ children }: { children: ReactNode }) {
  return (
    <div className="docs-table-wrap">
      <table className="docs-table">{children}</table>
    </div>
  );
}
