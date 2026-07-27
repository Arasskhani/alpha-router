import { authFetch } from "../api";

/**
 * Chat message export helpers (CSV on the client, PDF via the backend
 * Playwright renderer for best Persian/RTL quality).
 *
 * Security notes:
 * - CSV is built entirely client-side from the assistant message text; no
 *   third party receives the content.
 * - PDF is rendered by the authenticated backend, which HTML-escapes the
 *   markdown, disables JavaScript, and aborts all sub-resource requests
 *   (anti-SSRF). See `backend/app/services/chat_export_service.py`.
 */

// ---------------------------------------------------------------------------
// CSV
// ---------------------------------------------------------------------------

type CsvTable = { header: string[]; rows: string[][] };

function csvCell(value: string): string {
  const v = value ?? "";
  if (/[",\n\r]/.test(v)) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

function csvRow(cells: string[]): string {
  return cells.map(csvCell).join(",");
}

/** Parse a GitHub-flavored markdown pipe table into rows of cells. */
function parseMarkdownTable(block: string): CsvTable | null {
  const lines = block
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length < 2) return null;
  const isPipeRow = (l: string) => l.startsWith("|") || l.endsWith("|");
  if (!lines.every(isPipeRow)) return null;
  // Second line must be a separator like | --- | :---: |
  const sep = lines[1].replace(/^\|/, "").replace(/\|$/, "").split("|");
  if (!sep.every((c) => /^:?-+:?$/.test(c.trim()))) return null;

  const splitRow = (l: string) =>
    l.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

  const header = splitRow(lines[0]);
  const rows = lines.slice(2).map(splitRow);
  return { header, rows };
}

/**
 * Extract the best tabular content from a markdown assistant message.
 * Preference: first markdown pipe table -> first ```csv fenced block ->
 * full text as a single-column table.
 */
function extractCsvTables(content: string): CsvTable[] {
  const tables: CsvTable[] = [];

  // 1) Markdown pipe tables.
  const tableRe = /(^|\n)([ \t]*\|[^\n]+\n[ \t]*\|[ \t]*:?-+:?[^\n]*(?:\n[ \t]*\|[^\n]+)*)/g;
  let m: RegExpExecArray | null;
  while ((m = tableRe.exec(content)) !== null) {
    const t = parseMarkdownTable(m[2]);
    if (t) tables.push(t);
  }

  if (tables.length) return tables;

  // 2) Fenced ```csv blocks.
  const csvBlockRe = /```csv[ \t]*\r?\n([\s\S]*?)```/gi;
  while ((m = csvBlockRe.exec(content)) !== null) {
    const raw = m[1].trim();
    if (!raw) continue;
    const lines = raw.split(/\r?\n/).filter((l) => l.trim().length > 0);
    const rows = lines.map((l) => l.split(",").map((c) => c.trim()));
    if (rows.length) {
      tables.push({ header: rows[0], rows: rows.slice(1) });
    }
  }

  if (tables.length) return tables;

  // 3) Fallback: whole text as a single-column "Content" table.
  const text = content.trim();
  if (!text) return [];
  return [{ header: ["Content"], rows: text.split(/\r?\n/).map((l) => [l]) }];
}

export function markdownToCsv(content: string): string {
  const tables = extractCsvTables(content);
  if (!tables.length) return "";
  // Concatenate multiple tables with a blank line between sections.
  return tables
    .map((t) => {
      const lines = [csvRow(t.header), ...t.rows.map(csvRow)];
      return lines.join("\r\n");
    })
    .join("\r\n\r\n");
}

export function downloadCsv(filename: string, content: string): void {
  const csv = markdownToCsv(content);
  if (!csv) return;
  // Prepend BOM so Excel detects UTF-8 (important for Persian text).
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// PDF (backend renderer)
// ---------------------------------------------------------------------------

export async function exportMessagePdf(
  content: string,
  title?: string,
): Promise<void> {
  await _postBlobDownload(
    "/api/chat/export/pdf",
    { content, title },
    title,
    "pdf",
  );
}

export async function exportMessageDocx(
  content: string,
  title?: string,
): Promise<void> {
  await _postBlobDownload(
    "/api/chat/export/docx",
    { content, title },
    title,
    "docx",
  );
}

async function _postBlobDownload(
  path: string,
  body: { content: string; title?: string },
  title: string | undefined,
  ext: string,
): Promise<void> {
  const res = await authFetch(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const text = await res.text();
      const j = JSON.parse(text) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safe =
    (title || "chat-export")
      .replace(/[^\p{L}\p{N}_-]+/gu, "_")
      .slice(0, 60) || "chat-export";
  a.download = `${safe}.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
