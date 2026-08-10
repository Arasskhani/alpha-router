/** Client helpers for explicit user memories (`/api/user/memories`). */

import { api } from "../api";

export type UserMemory = {
  id: string;
  content: string;
  enabled: boolean;
  source_session_id?: string | null;
  created_at: number;
  updated_at: number;
};

export type UserProfileContext = {
  company: string | null;
  department: string | null;
  job_title: string | null;
  reporting_to: string | null;
};

function trimOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export type UserMemoriesPayload = {
  memories: UserMemory[];
  total: number;
  profile?: UserProfileContext;
};

export const MAX_MEMORY_CHARS = 500;

export function normalizeMemoryDraft(raw: string): string {
  return raw.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").replace(/\s+/g, " ").trim();
}

export async function fetchUserMemoriesBundle(): Promise<{
  memories: UserMemory[];
  profile: UserProfileContext;
}> {
  const data = await api<UserMemoriesPayload>("/api/user/memories");
  return {
    memories: Array.isArray(data.memories) ? data.memories : [],
    profile: {
      company: trimOrNull(data.profile?.company),
      department: trimOrNull(data.profile?.department),
      job_title: trimOrNull(data.profile?.job_title),
      reporting_to: trimOrNull(data.profile?.reporting_to),
    },
  };
}

export async function listUserMemories(): Promise<UserMemory[]> {
  const data = await fetchUserMemoriesBundle();
  return data.memories;
}

export async function createUserMemory(
  content: string,
  opts?: { source_session_id?: string | null },
): Promise<UserMemory> {
  return api<UserMemory>("/api/user/memories", {
    method: "POST",
    body: JSON.stringify({
      content,
      source_session_id: opts?.source_session_id || undefined,
    }),
  });
}

export async function updateUserMemory(
  id: string,
  updates: { content?: string; enabled?: boolean },
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
