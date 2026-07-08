/** Alpha Router media files are served from an authenticated API route. */

export function isAlphaRouterMediaFileUrl(url: string): boolean {
  if (!url) return false;
  try {
    const path = url.startsWith("http") ? new URL(url).pathname : url.split("?")[0];
    return /^\/api\/chat\/media\/\d+\/file$/.test(path);
  } catch {
    return /^\/api\/chat\/media\/\d+\/file(?:\?.*)?$/.test(url);
  }
}

export async function fetchAuthenticatedMediaBlob(url: string): Promise<Blob> {
  const token = localStorage.getItem("alpha_router_token");
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const j = JSON.parse(text) as { detail?: string };
      throw new Error(j.detail || text);
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
      throw new Error(text || `Failed to load media (${res.status})`);
    }
  }
  return res.blob();
}

export async function fetchAuthenticatedMediaObjectUrl(url: string): Promise<string> {
  const blob = await fetchAuthenticatedMediaBlob(url);
  return URL.createObjectURL(blob);
}
