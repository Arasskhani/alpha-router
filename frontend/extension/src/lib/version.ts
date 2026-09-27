/** Compare Chrome extension versions ("1.0.3.12"): negative, zero or positive. */
export function compareVersions(a: string, b: string): number {
  const left = a.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const right = b.split(".").map((part) => Number.parseInt(part, 10) || 0);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/**
 * This copy's package version, for the server's record of who runs what.
 * Undefined wherever the manifest cannot be read, so a caller that only wants
 * to mention it never fails for the want of it.
 */
export function packageVersion(): string | undefined {
  try {
    // Through globalThis: a bare `chrome` throws where the global is not declared at all.
    const runtime = (globalThis as { chrome?: { runtime?: { getManifest?: () => { version?: string } } } }).chrome?.runtime;
    return runtime?.getManifest?.().version || undefined;
  } catch {
    return undefined;
  }
}
