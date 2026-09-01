import { authFetch } from "../api";
function csvCell(value) {
    const v = value ?? "";
    if (/[",\n\r]/.test(v)) {
        return `"${v.replace(/"/g, '""')}"`;
    }
    return v;
}
function csvRow(cells) {
    return cells.map(csvCell).join(",");
}
/** Parse a GitHub-flavored markdown pipe table into rows of cells. */
function parseMarkdownTable(block) {
    const lines = block
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0);
    if (lines.length < 2)
        return null;
    const isPipeRow = (l) => l.startsWith("|") || l.endsWith("|");
    if (!lines.every(isPipeRow))
        return null;
    // Second line must be a separator like | --- | :---: |
    const sep = lines[1].replace(/^\|/, "").replace(/\|$/, "").split("|");
    if (!sep.every((c) => /^:?-+:?$/.test(c.trim())))
        return null;
    const splitRow = (l) => l.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
    const header = splitRow(lines[0]);
    const rows = lines.slice(2).map(splitRow);
    return { header, rows };
}
/**
 * Extract the best tabular content from a markdown assistant message.
 * Preference: first markdown pipe table -> first ```csv fenced block ->
 * full text as a single-column table.
 */
function extractCsvTables(content) {
    const tables = [];
    // 1) Markdown pipe tables.
    const tableRe = /(^|\n)([ \t]*\|[^\n]+\n[ \t]*\|[ \t]*:?-+:?[^\n]*(?:\n[ \t]*\|[^\n]+)*)/g;
    let m;
    while ((m = tableRe.exec(content)) !== null) {
        const t = parseMarkdownTable(m[2]);
        if (t)
            tables.push(t);
    }
    if (tables.length)
        return tables;
    // 2) Fenced ```csv blocks.
    const csvBlockRe = /```csv[ \t]*\r?\n([\s\S]*?)```/gi;
    while ((m = csvBlockRe.exec(content)) !== null) {
        const raw = m[1].trim();
        if (!raw)
            continue;
        const lines = raw.split(/\r?\n/).filter((l) => l.trim().length > 0);
        const rows = lines.map((l) => l.split(",").map((c) => c.trim()));
        if (rows.length) {
            tables.push({ header: rows[0], rows: rows.slice(1) });
        }
    }
    if (tables.length)
        return tables;
    // 3) Fallback: whole text as a single-column "Content" table.
    const text = content.trim();
    if (!text)
        return [];
    return [{ header: ["Content"], rows: text.split(/\r?\n/).map((l) => [l]) }];
}
export function markdownToCsv(content) {
    const tables = extractCsvTables(content);
    if (!tables.length)
        return "";
    // Concatenate multiple tables with a blank line between sections.
    return tables
        .map((t) => {
        const lines = [csvRow(t.header), ...t.rows.map(csvRow)];
        return lines.join("\r\n");
    })
        .join("\r\n\r\n");
}
export function downloadCsv(filename, content) {
    const csv = markdownToCsv(content);
    if (!csv)
        return;
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
export function downloadTxt(filename, content) {
    const text = (content || "").trim();
    if (!text)
        return;
    // BOM helps editors (and Excel) detect UTF-8 for Persian text.
    const blob = new Blob(["\uFEFF" + text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safe = (filename || "chat-export")
        .replace(/[^\p{L}\p{N}_-]+/gu, "_")
        .slice(0, 60) || "chat-export";
    a.download = safe.endsWith(".txt") ? safe : `${safe}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
// ---------------------------------------------------------------------------
// PDF (backend renderer)
// ---------------------------------------------------------------------------
export async function exportMessagePdf(content, title) {
    await _postBlobDownload("/api/chat/export/pdf", { content, title }, title, "pdf");
}
export async function exportMessageDocx(content, title) {
    await _postBlobDownload("/api/chat/export/docx", { content, title }, title, "docx");
}
async function _postBlobDownload(path, body, title, ext) {
    const res = await authFetch(path, {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
            const text = await res.text();
            const j = JSON.parse(text);
            if (typeof j.detail === "string")
                detail = j.detail;
        }
        catch {
            /* ignore */
        }
        throw new Error(detail);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safe = (title || "chat-export")
        .replace(/[^\p{L}\p{N}_-]+/gu, "_")
        .slice(0, 60) || "chat-export";
    a.download = `${safe}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
