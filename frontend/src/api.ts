const token = () => localStorage.getItem("nitro_token");

/** Turn FastAPI / fetch errors into a user-visible string. */
export function formatApiError(err: unknown): string {
  if (err instanceof Error) {
    const msg = err.message;
    if (msg && msg !== "[object Object]") return msg;
  }
  if (err && typeof err === "object") {
    const detail = (err as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; revision?: number };
      if (d.message) {
        return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
      }
      try {
        return JSON.stringify(detail);
      } catch {
        /* fall through */
      }
    }
  }
  if (typeof err === "string") return err;
  return "Request failed";
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown; message?: string };
    const detail = j.detail ?? j.message;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; revision?: number };
      if (d.message) {
        return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
      }
      return JSON.stringify(detail);
    }
    return text || res.statusText;
  } catch {
    return text || res.statusText;
  }
}

/** True when the API rejected the request due to missing or invalid auth. */
export function isApiAuthError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  return (err as { status?: number }).status === 401;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const err = new Error(await parseError(res)) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
