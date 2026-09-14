import { api } from "../api";

export const MAX_ROOM_HANDOFF_BRIEF = 8000;

export type ProjectRoom = {
  id: string;
  title: string;
  messageCount: number;
  revision: number;
  channelKind: "member";
  createdByUserId?: number | null;
  createdAt?: number | null;
  updatedAt?: number | null;
  lastMessageAt?: number | null;
};

export type ProjectRoomMessage = {
  id: string;
  role: "user";
  content: string;
  sequence?: number;
  authorDisplayName?: string | null;
  clientMessageId?: string | null;
  userId?: number | null;
  mine?: boolean;
  edited?: boolean;
  replyToMessageId?: string | null;
  replyToAuthor?: string | null;
  replyToContent?: string | null;
};

export type ProjectRoomSyncPayload = {
  serverTimeMs: number;
  aclVersion?: number;
  total: number;
  sessionIds: string[];
  sessions: ProjectRoom[];
  messages?: ProjectRoomMessage[];
  messageSessionId?: string | null;
  completeWindow?: boolean;
  goneSessionId?: string | null;
};

export type ProjectRoomHandoffResult = {
  targetSessionId: string;
  brief: string;
  sourceRoomId: string;
};

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function normalizeProjectRoom(raw: Record<string, unknown>): ProjectRoom {
  return {
    id: String(raw.id || ""),
    title: String(raw.title || "New room"),
    messageCount: Number(raw.messageCount || 0),
    revision: Number(raw.revision || 1),
    channelKind: "member",
    createdByUserId: asNumber(raw.createdByUserId) ?? null,
    createdAt: asNumber(raw.createdAt),
    updatedAt: asNumber(raw.updatedAt),
    lastMessageAt: asNumber(raw.lastMessageAt),
  };
}

export function normalizeProjectRoomMessage(raw: Record<string, unknown>): ProjectRoomMessage {
  return {
    id: String(raw.id || ""),
    role: "user",
    content: String(raw.content || ""),
    sequence: asNumber(raw.sequence) ?? undefined,
    authorDisplayName: raw.authorDisplayName == null ? null : String(raw.authorDisplayName),
    clientMessageId: raw.clientMessageId == null ? null : String(raw.clientMessageId),
    userId: asNumber(raw.userId),
    mine: Boolean(raw.mine),
    edited: Boolean(raw.edited),
    replyToMessageId: raw.replyToMessageId == null ? null : String(raw.replyToMessageId),
    replyToAuthor: raw.replyToAuthor == null ? null : String(raw.replyToAuthor),
    replyToContent: raw.replyToContent == null ? null : String(raw.replyToContent),
  };
}

export async function listProjectRooms(
  projectId: string,
  opts?: { limit?: number; offset?: number; q?: string },
): Promise<{ rooms: ProjectRoom[]; total: number }> {
  const params = new URLSearchParams();
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  if (opts?.q?.trim()) params.set("q", opts.q.trim());
  const qs = params.toString();
  const data = await api<{ rooms?: Record<string, unknown>[]; total?: number }>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms${qs ? `?${qs}` : ""}`,
  );
  return {
    rooms: (data.rooms || []).map((row) => normalizeProjectRoom(row)),
    total: Number(data.total || 0),
  };
}

export async function syncProjectRooms(
  projectId: string,
  opts?: { since?: number; sessionId?: string | null; afterSequence?: number | null },
): Promise<ProjectRoomSyncPayload> {
  const params = new URLSearchParams();
  if (opts?.since != null) params.set("since", String(opts.since));
  if (opts?.sessionId) params.set("session_id", opts.sessionId);
  if (opts?.afterSequence != null) params.set("after_sequence", String(opts.afterSequence));
  const qs = params.toString();
  const data = await api<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/sync${qs ? `?${qs}` : ""}`,
  );
  return {
    serverTimeMs: Number(data.serverTimeMs || 0),
    aclVersion: asNumber(data.aclVersion) ?? undefined,
    total: Number(data.total || 0),
    sessionIds: Array.isArray(data.sessionIds) ? data.sessionIds.map(String) : [],
    sessions: Array.isArray(data.sessions)
      ? (data.sessions as Record<string, unknown>[]).map((row) => normalizeProjectRoom(row))
      : [],
    messages: Array.isArray(data.messages)
      ? (data.messages as Record<string, unknown>[]).map((row) => normalizeProjectRoomMessage(row))
      : [],
    messageSessionId: data.messageSessionId == null ? null : String(data.messageSessionId),
    completeWindow: Boolean(data.completeWindow),
    goneSessionId: data.goneSessionId == null ? null : String(data.goneSessionId),
  };
}

export async function createProjectRoom(
  projectId: string,
  body?: { id?: string; title?: string },
): Promise<ProjectRoom> {
  const data = await api<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );
  return normalizeProjectRoom(data);
}
export async function deleteProjectRoom(
  projectId: string,
  roomId: string,
): Promise<{ deleted: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}`,
    { method: "DELETE" },
  );
}

export async function listProjectRoomMessages(
  projectId: string,
  roomId: string,
  opts?: { limit?: number; before?: number },
): Promise<{ messages: ProjectRoomMessage[]; hasMore: boolean }> {
  const params = new URLSearchParams();
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.before != null) params.set("before", String(opts.before));
  const qs = params.toString();
  const data = await api<{ messages?: Record<string, unknown>[]; hasMore?: boolean; has_more?: boolean }>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages${qs ? `?${qs}` : ""}`,
  );
  return {
    messages: (data.messages || []).map((row) => normalizeProjectRoomMessage(row)),
    hasMore: Boolean(data.hasMore ?? data.has_more),
  };
}

export async function appendProjectRoomMessage(
  projectId: string,
  roomId: string,
  body: { content: string; clientMessageId?: string; replyToMessageId?: string },
): Promise<ProjectRoomMessage> {
  const data = await api<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return normalizeProjectRoomMessage(data);
}

export async function updateProjectRoomMessage(
  projectId: string,
  roomId: string,
  messageId: string,
  body: { content: string },
): Promise<ProjectRoomMessage> {
  const data = await api<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages/${encodeURIComponent(messageId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
  return normalizeProjectRoomMessage(data);
}

export async function deleteProjectRoomMessage(
  projectId: string,
  roomId: string,
  messageId: string,
): Promise<{ deleted: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages/${encodeURIComponent(messageId)}`,
    { method: "DELETE" },
  );
}

export async function createProjectRoomHandoff(
  projectId: string,
  roomId: string,
  body: { title?: string; brief: string },
): Promise<ProjectRoomHandoffResult> {
  const data = await api<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/handoffs`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return {
    targetSessionId: String(data.targetSessionId || ""),
    brief: String(data.brief || ""),
    sourceRoomId: String(data.sourceRoomId || roomId),
  };
}
