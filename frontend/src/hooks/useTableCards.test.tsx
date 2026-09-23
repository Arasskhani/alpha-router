/**
 * @vitest-environment happy-dom
 */
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PHONE_QUERY } from "./useMediaQuery";
import { useTableCards } from "./useTableCards";

let host: HTMLDivElement;
let root: Root;
let addRow: () => void = () => {};

function UsersTable() {
  const ref = useTableCards<HTMLTableElement>();
  const [rows, setRows] = useState(["sara", "reza"]);
  useEffect(() => {
    addRow = () => setRows((r) => [...r, "maryam"]);
  }, []);
  return (
    <table ref={ref} className="data-table data-table--cards">
      <thead>
        <tr>
          <th>
            <input type="checkbox" aria-label="Select all" />
          </th>
          <th>User</th>
          <th className="col-md">Email</th>
          <th>Role</th>
          <th className="col-actions">Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((name) => (
          <tr key={name}>
            <td>
              <input type="checkbox" aria-label={`Select ${name}`} />
            </td>
            <td>{name}</td>
            <td className="col-md">{name}@example.com</td>
            <td>User</td>
            <td className="col-actions">
              <button type="button">Actions</button>
            </td>
          </tr>
        ))}
        <tr>
          <td colSpan={5}>No more users.</td>
        </tr>
      </tbody>
    </table>
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const cells = (row: number) => [...host.querySelectorAll("tbody tr")[row].querySelectorAll("td")];

describe("useTableCards", () => {
  it("copies each header into its cells and marks the card roles", async () => {
    await act(async () => root.render(<UsersTable />));
    const first = cells(0);
    expect(first.map((td) => td.getAttribute("data-label"))).toEqual(["", "User", "Email", "Role", "Actions"]);
    expect(first.map((td) => td.getAttribute("data-card-role"))).toEqual(["select", "title", "field", "field", "actions"]);
    const headers = [...host.querySelectorAll("thead th")];
    expect(headers.map((th) => th.getAttribute("data-card-role"))).toEqual(["select", "title", "field", "field", "actions"]);
  });

  it("counts a tap on the phone's Select all caption as a tap on the box", async () => {
    const real = window.matchMedia;
    let phone = true;
    window.matchMedia = ((query: string) => ({ matches: phone && query === PHONE_QUERY })) as typeof window.matchMedia;
    try {
      await act(async () => root.render(<UsersTable />));
      const cell = host.querySelector<HTMLElement>("thead th")!;
      const box = cell.querySelector("input")!;
      await act(async () => cell.click());
      expect(box.checked).toBe(true);
      // A tap on the box is the box's own: it is not passed on a second time.
      await act(async () => box.click());
      expect(box.checked).toBe(false);
      // On a desktop there is no caption; a click beside the box does nothing.
      phone = false;
      await act(async () => cell.click());
      expect(box.checked).toBe(false);
      // A box the page has locked stays as it is: read-only admin takes it out of
      // reach with pointer-events: none, and a disabled box is disabled.
      phone = true;
      box.style.pointerEvents = "none";
      await act(async () => cell.click());
      expect(box.checked).toBe(false);
      box.style.pointerEvents = "";
      box.disabled = true;
      await act(async () => cell.click());
      expect(box.checked).toBe(false);
    } finally {
      window.matchMedia = real;
    }
  });

  it("counts a tap anywhere in a card's select corner as a tap on that card's box", async () => {
    const real = window.matchMedia;
    let phone = true;
    window.matchMedia = ((query: string) => ({ matches: phone && query === PHONE_QUERY })) as typeof window.matchMedia;
    try {
      await act(async () => root.render(<UsersTable />));
      const corner = cells(0)[0];
      const box = corner.querySelector("input")!;
      await act(async () => corner.click());
      expect(box.checked).toBe(true);
      expect(cells(1)[0].querySelector("input")!.checked).toBe(false);
      // Elsewhere in the card a tap is not a tap on the box.
      await act(async () => cells(0)[1].click());
      expect(box.checked).toBe(true);
      // On a desktop the cell is a table cell like any other.
      phone = false;
      await act(async () => corner.click());
      expect(box.checked).toBe(true);
    } finally {
      window.matchMedia = real;
    }
  });

  it("leaves a box inside a label to the label, which ticks it once", async () => {
    const real = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: query === PHONE_QUERY })) as typeof window.matchMedia;
    function Labelled() {
      const ref = useTableCards<HTMLTableElement>();
      return (
        <table ref={ref} className="data-table data-table--cards">
          <thead>
            <tr>
              <th />
              <th>Model</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <label>
                  <input type="checkbox" /> <span>Pick</span>
                </label>
              </td>
              <td>mock-gpt-4o</td>
            </tr>
          </tbody>
        </table>
      );
    }
    try {
      await act(async () => root.render(<Labelled />));
      expect(cells(0)[0].getAttribute("data-card-role")).toBe("select");
      await act(async () => host.querySelector<HTMLElement>("tbody label span")!.click());
      expect(host.querySelector<HTMLInputElement>("tbody input")!.checked).toBe(true);
    } finally {
      window.matchMedia = real;
    }
  });

  it("treats a cell that spans the table as full width, without a label", async () => {
    await act(async () => root.render(<UsersTable />));
    const empty = cells(2)[0];
    expect(empty.getAttribute("data-card-role")).toBe("full");
    expect(empty.hasAttribute("data-label")).toBe(false);
  });

  it("labels rows that arrive later", async () => {
    await act(async () => root.render(<UsersTable />));
    await act(async () => addRow());
    // MutationObserver callbacks are microtasks; let them run.
    await act(async () => {
      await Promise.resolve();
    });
    const added = [...host.querySelectorAll("tbody tr")].find((tr) => tr.textContent?.includes("maryam"))!;
    expect([...added.querySelectorAll("td")].map((td) => td.getAttribute("data-label"))).toEqual([
      "",
      "User",
      "Email",
      "Role",
      "Actions",
    ]);
  });

  it("labels a table that appears only after its data has loaded", async () => {
    let show: () => void = () => {};
    function Later() {
      const ref = useTableCards<HTMLTableElement>();
      const [ready, setReady] = useState(false);
      useEffect(() => {
        show = () => setReady(true);
      }, []);
      return ready ? (
        <table ref={ref} className="data-table data-table--cards">
          <thead>
            <tr>
              <th>Name</th>
              <th>Monthly budget</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Standard</td>
              <td>$100</td>
            </tr>
          </tbody>
        </table>
      ) : (
        <p>Loading…</p>
      );
    }
    await act(async () => root.render(<Later />));
    await act(async () => show());
    expect(cells(0).map((td) => td.getAttribute("data-label"))).toEqual(["Name", "Monthly budget"]);
    expect(cells(0)[0].getAttribute("data-card-role")).toBe("title");
  });

  it("states the table's semantics explicitly, so a changed display cannot drop them", async () => {
    await act(async () => root.render(<UsersTable />));
    const table = host.querySelector("table")!;
    expect(table.getAttribute("role")).toBe("table");
    expect(table.querySelector("tbody")?.getAttribute("role")).toBe("rowgroup");
    expect(table.querySelector("thead th")?.getAttribute("role")).toBe("columnheader");
    expect(table.querySelector("tbody tr")?.getAttribute("role")).toBe("row");
    expect(table.querySelector("tbody td")?.getAttribute("role")).toBe("cell");
  });
});
