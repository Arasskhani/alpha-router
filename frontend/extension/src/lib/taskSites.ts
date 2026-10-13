/**
 * The sites a task names: "search wikipedia for…", "open digikala.com and…",
 * «در دیجی‌کالا قیمت … را پیدا کن». The user typed the task, so going to a site
 * it names is going where the user asked - the run's first navigation there
 * need not ask about "another site". Only what the user wrote counts; a page
 * can never add a site this way. The site rules still apply to every one.
 */

import { siteOf } from "./sites";

/** Well-known services by the names people use for them, in English and in Persian. */
const KNOWN: Array<[RegExp, string]> = [
  [/\b(google|gmail)\b|گوگل|جیمیل/, "google.com"],
  [/\byoutube\b|یوتیوب|یوتوب/, "youtube.com"],
  [/\bwikipedia\b|ویکی ?پدیا/, "wikipedia.org"],
  [/\bgithub\b|گیت ?هاب/, "github.com"],
  [/\bgitlab\b|گیت ?لب/, "gitlab.com"],
  [/\blinkedin\b|لینکدین|لینکداین/, "linkedin.com"],
  [/\bstack ?overflow\b|استک ?اورفلو/, "stackoverflow.com"],
  [/\bdigikala\b|دیجی ?کالا/, "digikala.com"],
  [/\breddit\b|ردیت/, "reddit.com"],
  [/\bbing\b|بینگ/, "bing.com"],
  [/\bduckduckgo\b/, "duckduckgo.com"],
  [/\bamazon\b|آمازون/, "amazon.com"],
];

/**
 * A domain written in the task: labels and a top-level domain of letters,
 * with or without a scheme - not the part after an @ (an email address is a
 * person, not a site to visit).
 */
const DOMAIN = /(?<![@\w.-])(?:https?:\/\/)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?![\w-]|\.[a-z0-9])/g;

/** What ends a file's name rather than a domain: "report.pdf" is a file. */
const FILE_ENDINGS = new Set([
  "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "json", "xml", "html", "htm", "md",
  "png", "jpg", "jpeg", "gif", "svg", "webp", "zip", "rar", "mp3", "mp4", "mov", "exe", "js", "ts", "py",
]);

/** The task as the lists read it: lower case, the joiners and marks between Persian letters read as a space. */
function readable(task: string): string {
  return task.normalize("NFKC").toLowerCase().replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/\p{Cf}/gu, " ");
}

/** The sites (as siteOf names them) the task names, each once. */
export function namedSites(task: string): string[] {
  const text = readable(task);
  const found = new Set<string>();
  for (const match of text.matchAll(DOMAIN)) {
    const ending = match[1].slice(match[1].lastIndexOf(".") + 1);
    if (!match[0].startsWith("http") && FILE_ENDINGS.has(ending)) continue;
    found.add(siteOf(match[1]));
  }
  for (const [words, site] of KNOWN) if (words.test(text)) found.add(site);
  return [...found];
}
