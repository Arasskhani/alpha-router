/**
 * Support (user side): the times, refusals and image checks the list, the new
 * ticket dialog and the conversation share.
 */
import { formatLocalDate, parseApiDateTime } from "../../lib/dateTime";
import { TicketsApiError, type SupportLimits } from "../../lib/tickets";

const MINUTE = 60_000;
const DAY = 86_400_000;

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function isYesterday(d: Date, now: Date): boolean {
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  return sameDay(d, y);
}

function clock(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "09:12" today, "yesterday 09:12", "21 Oct 09:12" (with the year when it is not this one). */
export function messageTime(iso: string | null | undefined): string {
  const d = parseApiDateTime(iso);
  if (!d) return "";
  const now = new Date();
  if (sameDay(d, now)) return clock(d);
  if (isYesterday(d, now)) return `yesterday ${clock(d)}`;
  const day = d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${day} ${clock(d)}`;
}

/** "today 09:12", "yesterday 09:12", "21 Oct 09:12". */
export function openedTime(iso: string | null | undefined): string {
  const d = parseApiDateTime(iso);
  if (!d) return "";
  return sameDay(d, new Date()) ? `today ${clock(d)}` : messageTime(iso);
}

/** "just now", "25 min ago", "3 h ago", "yesterday", "4 days ago", else the date. */
export function agoText(iso: string | null | undefined): string {
  const d = parseApiDateTime(iso);
  if (!d) return "";
  const now = new Date();
  const minutes = Math.floor((now.getTime() - d.getTime()) / MINUTE);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (sameDay(d, now)) return `${Math.floor(minutes / 60)} h ago`;
  if (isYesterday(d, now)) return "yesterday";
  const days = Math.round((now.getTime() - d.getTime()) / DAY);
  if (days < 30) return `${days} days ago`;
  return `on ${formatLocalDate(iso)}`;
}

/** Whole days from now until `iso`, rounded up; 0 once it has passed; null without a date. */
export function daysUntil(iso: string | null | undefined): number | null {
  const d = parseApiDateTime(iso);
  if (!d) return null;
  return Math.max(0, Math.ceil((d.getTime() - Date.now()) / DAY));
}

/** "Thu 29 Oct" (in the browser's own order). */
export function dayLabel(iso: string | null | undefined): string {
  const d = parseApiDateTime(iso);
  if (!d) return "";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "SK" for Sara Karimi. */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  return words
    .slice(0, 2)
    .map((w) => [...w][0] ?? "")
    .join("")
    .toUpperCase();
}

/** Support is off: every endpoint but /status answers this. */
export function isTicketsDisabled(err: unknown): boolean {
  return err instanceof TicketsApiError && err.status === 403 && err.code === "tickets_disabled";
}

/** What Python's str.splitlines() breaks on (the server joins the parts with a space). */
const LINE_BREAKS = new Set(["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]);

/**
 * A file name as the server reports it back (`file` on image_rejected): the
 * last path part, line breaks made spaces, trimmed, at most 255 characters.
 */
export function serverFileName(name: string): string {
  const base = (name.replace(/\\/g, "/").split("/").pop() ?? "").trim();
  const oneLine = Array.from(base.replace(/\r\n/g, "\n"), (ch) => (LINE_BREAKS.has(ch) ? " " : ch)).join("");
  return Array.from(oneLine || "image").slice(0, 255).join("");
}

/** The server's refusal without the file name it starts with ("logo.svg: only images…" → "only images…"). */
function withoutFileName(message: string, file: string): string {
  return file && message.startsWith(`${file}: `) ? message.slice(file.length + 2) : message;
}

/** What a person reads when the server refuses; `file` names the image for image_rejected. */
export function supportErrorText(err: unknown, limits?: SupportLimits | null): string {
  if (!(err instanceof TicketsApiError)) {
    return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
  }
  const file = typeof err.data.file === "string" ? err.data.file : "";
  switch (err.code) {
    case "ticket_rate_limited":
      return "You have opened several tickets in the last hour. Wait a little, then try again.";
    case "too_many_open":
      return "You already have the most open tickets allowed. Mark the ones that are fixed as resolved, or wait for an answer, then open a new one.";
    case "reopen_window_passed":
      return "This ticket can no longer be reopened. Open a new ticket if you still need help.";
    case "image_rejected":
      return file
        ? `“${file}” was not accepted: ${withoutFileName(err.message, file)}`
        : `An image was not accepted: ${err.message}`;
    case "invalid_category":
      return "That category is no longer offered. Pick another one.";
    case "tickets_disabled":
      return "Support is turned off by your administrator.";
    default:
      break;
  }
  if (err.status === 413) {
    return limits ? `An image is larger than ${limits.max_image_mb} MB.` : "An image is too large.";
  }
  if (err.status === 429) return "Too many requests. Wait a little, then try again.";
  if (err.status === 404) return "This ticket was not found.";
  if (err.status === 422) {
    return err.serverMessage ? err.message : "Something in the form is not right. Check the fields and try again.";
  }
  return err.message || `Request failed (${err.status}).`;
}

/** The extensions a picker accepts: an allowed jpg also accepts .jpeg. */
export function imageExtensions(types: string[]): string[] {
  const out = types.map((t) => t.toLowerCase());
  if (out.includes("jpg") && !out.includes("jpeg")) out.push("jpeg");
  return out;
}

/** "PNG, JPG, WEBP, GIF" */
export function imageTypesLabel(types: string[]): string {
  return types.map((t) => t.toUpperCase()).join(", ");
}

export type ImageRefusal = { name: string; reason: string };

/** Split picked files into the ones to keep and the ones refused, with a short reason each. */
export function checkImages(
  files: File[],
  alreadyKept: number,
  limits: SupportLimits,
): { kept: File[]; refused: ImageRefusal[] } {
  const allowed = imageExtensions(limits.image_types);
  const maxBytes = limits.max_image_mb * 1024 * 1024;
  const kept: File[] = [];
  const refused: ImageRefusal[] = [];
  for (const file of files) {
    const dot = file.name.lastIndexOf(".");
    const ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : "";
    if (!allowed.includes(ext)) refused.push({ name: file.name, reason: "not allowed" });
    else if (file.size > maxBytes) refused.push({ name: file.name, reason: `over ${limits.max_image_mb} MB` });
    else if (alreadyKept + kept.length >= limits.max_images)
      refused.push({ name: file.name, reason: `${limits.max_images} images at most` });
    else kept.push(file);
  }
  return { kept, refused };
}
