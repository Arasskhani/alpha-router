import { useCallback, useRef } from "react";

/**
 * Label a table's cells so that, on a phone, CSS can draw each row as a card.
 *
 * A `table.data-table--cards` becomes, under 768px (styles.css), a list of
 * cards: each cell on its own line as "label: value", the first column as the
 * card's title, the Actions cell in its top corner and the select checkbox
 * beside the title. CSS cannot read a column's header from a cell, so this
 * copies each header's text into its cells' `data-label` and marks those
 * roles in `data-card-role`. It runs again whenever rows change, and it sets
 * the native roles explicitly (table, row, cell…), because some browsers drop
 * a table's semantics once its `display` is changed.
 *
 * On a desktop the attributes are unused; the table looks as it always did.
 */
export function useTableCards<T extends HTMLTableElement>() {
  const observerRef = useRef<MutationObserver | null>(null);

  // A callback ref, not an effect: many pages render the table only once their
  // data has loaded, after the first render.
  return useCallback((table: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!table) return;
    labelTableCells(table);
    if (typeof MutationObserver === "undefined") return;
    // Only childList: the attributes set here do not wake the observer up again.
    const observer = new MutationObserver(() => labelTableCells(table));
    observer.observe(table, { childList: true, subtree: true });
    observerRef.current = observer;
  }, []);
}

type CardRole = "select" | "title" | "actions" | "full" | "field";

type Column = { label: string; role: CardRole };

function columnsOf(table: HTMLTableElement): Column[] {
  const headers = [...table.querySelectorAll<HTMLTableCellElement>("thead tr:last-child th")];
  let titleTaken = false;
  return headers.map((th) => {
    const label = (th.textContent ?? "").replace(/\s+/g, " ").trim();
    let role: CardRole = "field";
    if (th.classList.contains("col-actions")) role = "actions";
    else if (!label && th.querySelector('input[type="checkbox"]')) role = "select";
    else if (!label && headers.indexOf(th) === 0) role = "select";
    else if (!titleTaken && label) {
      role = "title";
      titleTaken = true;
    }
    return { label, role };
  });
}

function labelTableCells(table: HTMLTableElement): void {
  const columns = columnsOf(table);
  setRole(table, "table");
  table.querySelectorAll(":scope > thead, :scope > tbody, :scope > tfoot").forEach((group) => setRole(group, "rowgroup"));
  table.querySelectorAll("thead th").forEach((th) => setRole(th, "columnheader"));
  table.querySelectorAll("tr").forEach((tr) => setRole(tr, "row"));
  table.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
    let column = 0;
    for (const cell of [...row.cells]) {
      setRole(cell, "cell");
      if (cell.colSpan > 1) {
        setAttr(cell, "data-card-role", "full");
        cell.removeAttribute("data-label");
      } else {
        const info = columns[column];
        setAttr(cell, "data-card-role", info?.role ?? "field");
        setAttr(cell, "data-label", info?.label ?? "");
      }
      column += Math.max(1, cell.colSpan);
    }
  });
}

function setRole(el: Element, role: string) {
  setAttr(el, "role", role);
}

function setAttr(el: Element, name: string, value: string) {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}
