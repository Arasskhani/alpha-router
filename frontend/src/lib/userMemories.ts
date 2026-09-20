/** Client helpers for automatic user memories (`/api/user/memories`). */

import { api, authFetch } from "../api";

export type UserMemory = {
  id: string;
  content: string;
  enabled: boolean;
  origin?: string;
  category?: string;
  sensitivity?: string;
  source_session_id?: string | null;
  source_session_title?: string | null;
  created_at: number;
  updated_at: number;
  last_used_at?: number | null;
};

type UserMemoriesPayload = {
  memories: UserMemory[];
  total: number;
  limit?: number;
  offset?: number;
  auto_capture?: boolean;
  memory_enabled?: boolean;
  feature_enabled?: boolean;
  extraction_configured?: boolean;
};

export async function fetchUserMemoriesBundle(opts?: {
  limit?: number;
  offset?: number;
}): Promise<{
  memories: UserMemory[];
  total: number;
  auto_capture: boolean;
  memory_enabled: boolean;
  feature_enabled: boolean;
  extraction_configured: boolean;
}> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const data = await api<UserMemoriesPayload>(`/api/user/memories${qs ? `?${qs}` : ""}`);
  return {
    memories: Array.isArray(data.memories) ? data.memories : [],
    total: typeof data.total === "number" ? data.total : 0,
    auto_capture: data.auto_capture !== false,
    memory_enabled: data.memory_enabled !== false,
    feature_enabled: data.feature_enabled !== false,
    extraction_configured: data.extraction_configured !== false,
  };
}

export async function updateUserMemory(
  id: string,
  updates: { enabled?: boolean },
): Promise<UserMemory> {
  return api<UserMemory>(`/api/user/memories/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export async function deleteUserMemory(id: string): Promise<void> {
  await api(`/api/user/memories/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function deleteAllUserMemories(): Promise<number> {
  const data = await api<{ deleted?: number }>("/api/user/memories", { method: "DELETE" });
  return typeof data.deleted === "number" ? data.deleted : 0;
}

export async function exportUserMemories(): Promise<void> {
  const res = await authFetch("/api/user/memories/export");
  if (!res.ok) {
    throw new Error("Failed to export memories");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "alpharouter-memories.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
