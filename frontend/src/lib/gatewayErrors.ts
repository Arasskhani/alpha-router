/** Turn nginx/HTML gateway bodies into short user-facing errors. */

export function humanizeGatewayError(raw: string, status: number): string {
  const text = (raw || "").trim();
  const lower = text.toLowerCase();
  const looksHtml =
    lower.startsWith("<html") ||
    lower.startsWith("<!doctype") ||
    lower.includes("<center>nginx</center>") ||
    (lower.includes("<title>") && lower.includes("gateway"));

  if (
    status === 504 ||
    lower.includes("504 gateway") ||
    lower.includes("gateway time-out")
  ) {
    return "The request timed out at the gateway. Please retry.";
  }
  if (
    looksHtml &&
    (status === 413 ||
      lower.includes("413 request entity too large") ||
      lower.includes("request entity too large") ||
      lower.includes("client intended to send too large body"))
  ) {
    return "The upload is too large for the server limit. Try a smaller file or ask an admin to raise Maximum upload size.";
  }
  if (looksHtml) {
    return `Request failed (${status || "gateway"}).`;
  }
  return text || `Request failed (${status})`;
}
