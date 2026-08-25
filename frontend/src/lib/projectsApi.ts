import { api } from "../api";
import {
  normalizeProjectChatComposerPrefs,
  type ProjectChatComposerPrefs,
} from "./projectChatComposer";
import type { ChatToolsState } from "./chatTools";

export type ProjectRole = "primary_owner" | "owner" | "contributor" | "viewer";
export type ProjectVisibility = "private" | "public";
export type ProjectStatus = "active" | "archived" | "deletion_pending";

export function isProjectOwnerRole(role?: string | null): boolean {
  return role === "primary_owner" || role === "owner";
}

export function isPrimaryOwnerRole(role?: string | null): boolean {
  return role === "primary_owner";
}

export function projectRoleLabel(role?: string | null): string {
  if (role === "primary_owner") return "Primary Owner";
  if (role === "owner") return "Owner";
  if (role === "contributor") return "Contributor";
  if (role === "viewer") return "Viewer";
  return role ?? "";
}

export function assignableProjectRoles(actorRole?: string | null): ProjectRole[] {
  if (actorRole === "primary_owner") return ["owner", "contributor", "viewer"];
  if (actorRole === "owner") return ["contributor", "viewer"];
  return [];
}

export type ProjectRecord = {
  id: string;
  name: string;
  description?: string | null;
  status: ProjectStatus;
  visibility: ProjectVisibility;
  createdByUserId?: number | null;
  revision: number;
  aclVersion: number;
  createdAt?: string | null;
  updatedAt?: string | null;
  archivedAt?: string | null;
  myRole?: ProjectRole | null;
  isMember: boolean;
};

export function needsPublicTypedConfirm(
  current: ProjectVisibility,
  next: ProjectVisibility,
): boolean {
  return current !== "public" && next === "public";
}

export type ProjectOverviewCounts = {
  members: number;
  chats: number;
  resources: number;
  media: number;
};

export type ProjectOverviewUsage = {
  windowDays: number;
  totalCostUsd: number;
  mediaCostUsd: number;
  requests: number;
  totalTokens: number;
};

export type ProjectOverview = {
  project: ProjectRecord;
  counts: ProjectOverviewCounts;
  usage: ProjectOverviewUsage | null;
};

export type ProjectMemberRecord = {
  projectId: string;
  userId: number;
  role: ProjectRole;
  username?: string | null;
  displayName?: string | null;
  invitedByUserId?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type InvitableUser = {
  id: number;
  username: string;
  displayName?: string | null;
};

export type InvitationRecord = {
  id: string;
  projectId: string;
  role: ProjectRole;
  maxUses: number;
  useCount: number;
  expiresAt?: string | null;
  createdByUserId?: number | null;
  claimedByUserId?: number | null;
  claimedAt?: string | null;
  revokedAt?: string | null;
  createdAt?: string | null;
  isExpired: boolean;
  isRevoked: boolean;
  isExhausted: boolean;
  token?: string;
  emailSent?: boolean;
  emailWarning?: string | null;
};

export type ProjectConfig = {
  configVersionId?: string;
  revision: number;
  customPrompt?: string | null;
  memoryEnabled: boolean;
  memoryAutoCapture: boolean;
  groundingPolicy: Record<string, unknown>;
  createdAt?: string | null;
};

export const MAX_PROJECT_RESOURCE_UPLOAD_FILES = 20;

export type ProjectResource = {
  id: string;
  projectId: string;
  documentId: string;
  title: string;
  status: "processing" | "active" | "revoked" | "failed";
  versionStatus?: string | null;
  documentStatus?: string | null;
  failureReason?: string | null;
  uploadedByUserId?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export function projectResourceKnowledgeStatus(resource: ProjectResource): string {
  return (resource.versionStatus || resource.documentStatus || resource.status || "").trim();
}

export const PROJECT_RESOURCE_WAITING_LABEL = "Waiting for Admin Approval";

/** User-facing resource status: hide KB pipeline until the file is Published. */
export function projectResourceUserStatus(resource: ProjectResource): string {
  const kb = projectResourceKnowledgeStatus(resource).toLowerCase();
  if (kb === "published") return "Published";
  if (kb === "failed") return "Failed";
  if (kb === "revoked") return "Revoked";
  return PROJECT_RESOURCE_WAITING_LABEL;
}

export function projectResourceUserStatusTone(resource: ProjectResource): string {
  const kb = projectResourceKnowledgeStatus(resource).toLowerCase();
  if (kb === "published") return "published";
  if (kb === "failed" || kb === "revoked") return kb;
  return "review";
}

export function projectResourceTooManyFilesMessage(selectedCount: number): string {
  return (
    `You can upload at most ${MAX_PROJECT_RESOURCE_UPLOAD_FILES} files at a time. ` +
    `You selected ${selectedCount}. Please choose ${MAX_PROJECT_RESOURCE_UPLOAD_FILES} or fewer and try again.`
  );
}

export type ProjectMemoryOrigin = "manual" | "auto_chat";

export type ProjectMemory = {
  id: string;
  projectId: string;
  content: string;
  sourceType?: string | null;
  sourceId?: string | null;
  enabled: boolean;
  origin: ProjectMemoryOrigin;
  category: string;
  sensitivity?: string | null;
  salience?: number | null;
  confidence?: number | null;
  useCount?: number | null;
  sourceSessionId?: string | null;
  sourceSessionTitle?: string | null;
  sourceMessageId?: string | null;
  createdByUserId?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastUsedAt?: string | null;
};

export type MemoryGrant = {
  id: string;
  consumerProjectId: string;
  sourceProjectId: string;
  sourceProjectName?: string | null;
  actorUserId?: number | null;
  revokedAt?: string | null;
  createdAt?: string | null;
};

export async function listProjects(
  scope: "mine" | "explore" | "recent" = "mine",
  opts?: { limit?: number; offset?: number; q?: string },
): Promise<{ projects: ProjectRecord[]; total: number }> {
  const params = new URLSearchParams({ scope });
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.q) params.set("q", opts.q);
  return api(`/api/projects?${params.toString()}`);
}

export async function createProject(body: {
  name: string;
  description?: string | null;
  visibility?: ProjectVisibility;
}): Promise<ProjectRecord> {
  return api("/api/projects", { method: "POST", body: JSON.stringify(body) });
}

export async function getProject(projectId: string): Promise<ProjectRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}`);
}

export async function getProjectOverview(projectId: string): Promise<ProjectOverview> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/overview`);
}

export async function putProjectPrefs(
  projectId: string,
  body: { lastOpenedSessionId: string | null },
): Promise<{ lastOpenedSessionId: string | null; lastOpenedAt: number | null }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/prefs`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function getProjectChatComposerPrefs(
  projectId: string,
  sessionId: string,
): Promise<ProjectChatComposerPrefs> {
  const data = await api<Partial<ProjectChatComposerPrefs>>(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/composer-prefs`,
  );
  return normalizeProjectChatComposerPrefs(data);
}

export async function putProjectChatComposerPrefs(
  projectId: string,
  sessionId: string,
  body: {
    tools: ChatToolsState;
    toolsTouched: boolean;
    model: string;
    selectedAgentSlug: string | null;
  },
): Promise<ProjectChatComposerPrefs> {
  const data = await api<Partial<ProjectChatComposerPrefs>>(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/composer-prefs`,
    { method: "PUT", body: JSON.stringify(body) },
  );
  return normalizeProjectChatComposerPrefs(data);
}

export async function updateProject(
  projectId: string,
  body: { name?: string; description?: string | null; visibility?: ProjectVisibility },
): Promise<ProjectRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteProject(projectId: string): Promise<{ deleted: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

export async function archiveProject(projectId: string): Promise<ProjectRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/archive`, { method: "POST" });
}

export async function restoreProject(projectId: string): Promise<ProjectRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/restore`, { method: "POST" });
}

export async function purgeProject(projectId: string): Promise<{ purged: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/purge`, { method: "POST" });
}

export async function leaveProject(projectId: string): Promise<{ left: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/leave`, { method: "POST" });
}

export async function listMembers(
  projectId: string,
): Promise<{ members: ProjectMemberRecord[] }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/members`);
}

export async function addMember(
  projectId: string,
  userId: number,
  role: ProjectRole = "viewer",
): Promise<ProjectMemberRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/members`, {
    method: "POST",
    body: JSON.stringify({ userId, role }),
  });
}

export async function updateMemberRole(
  projectId: string,
  userId: number,
  role: ProjectRole,
): Promise<ProjectMemberRecord> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export async function removeMember(
  projectId: string,
  userId: number,
): Promise<{ removed: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/members/${userId}`, {
    method: "DELETE",
  });
}

export async function listInvitableUsers(
  projectId: string,
  q?: string,
  limit?: number,
): Promise<{ users: InvitableUser[] }> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (limit != null) params.set("limit", String(limit));
  const qs = params.toString();
  return api(`/api/projects/${encodeURIComponent(projectId)}/invitable-users${qs ? `?${qs}` : ""}`);
}

export async function listInvitations(
  projectId: string,
): Promise<{ invitations: InvitationRecord[] }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/invitations`);
}

export async function createInvitation(body: {
  projectId: string;
  role: ProjectRole;
  maxUses?: number;
  ttlDays?: number;
  notifyUserId?: number | null;
}): Promise<InvitationRecord> {
  return api(`/api/projects/${encodeURIComponent(body.projectId)}/invitations`, {
    method: "POST",
    body: JSON.stringify({
      role: body.role,
      maxUses: body.maxUses ?? 1,
      ttlDays: body.ttlDays ?? 7,
      notifyUserId: body.notifyUserId ?? undefined,
    }),
  });
}

export async function revokeInvitation(
  projectId: string,
  invitationId: string,
): Promise<{ revoked: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/invitations/${encodeURIComponent(invitationId)}`,
    { method: "DELETE" },
  );
}

export async function claimInvitation(token: string): Promise<ProjectRecord> {
  return api("/api/projects/invitations/claim", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function getProjectConfig(projectId: string): Promise<ProjectConfig> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/config`);
}

export async function updateProjectConfig(
  projectId: string,
  body: {
    customPrompt?: string | null;
    memoryEnabled?: boolean;
    memoryAutoCapture?: boolean;
    groundingPolicy?: Record<string, unknown>;
  },
): Promise<ProjectConfig> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/config`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export type ProjectConfigVersion = {
  id: string;
  projectId: string;
  revision: number;
  customPrompt?: string | null;
  memoryEnabled: boolean;
  memoryAutoCapture: boolean;
  groundingPolicy: Record<string, unknown>;
  createdByUserId?: number | null;
  createdAt?: string | null;
};

export async function listProjectConfigVersions(
  projectId: string,
): Promise<{ versions: ProjectConfigVersion[]; total: number }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/config/versions`);
}

export function groundingTogglesFromPolicy(policy?: Record<string, unknown> | null): {
  useProjectResources: boolean;
  useGrantedMemory: boolean;
} {
  const src = policy ?? {};
  return {
    useProjectResources: src.useProjectResources !== false,
    useGrantedMemory: src.useGrantedMemory !== false,
  };
}

export function groundingPolicyFromToggles(opts: {
  useProjectResources: boolean;
  useGrantedMemory: boolean;
}): Record<string, boolean> {
  return {
    useProjectResources: opts.useProjectResources,
    useGrantedMemory: opts.useGrantedMemory,
  };
}

export async function listProjectResources(
  projectId: string,
  opts?: { status?: string; limit?: number; offset?: number },
): Promise<{ resources: ProjectResource[]; total: number }> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return api(`/api/projects/${encodeURIComponent(projectId)}/resources${qs ? `?${qs}` : ""}`);
}

export async function uploadProjectResource(
  projectId: string,
  file: File,
  title?: string,
): Promise<Record<string, unknown>> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  return api(`/api/projects/${encodeURIComponent(projectId)}/resources`, {
    method: "POST",
    body: form,
  });
}

export async function deleteProjectResource(
  projectId: string,
  resourceId: string,
): Promise<{ deleted: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/resources/${encodeURIComponent(resourceId)}`, {
    method: "DELETE",
  });
}

export async function listProjectMemories(
  projectId: string,
  opts?: {
    origin?: "manual" | "auto";
    category?: string;
    limit?: number;
    offset?: number;
  },
): Promise<{ memories: ProjectMemory[]; total: number }> {
  const params = new URLSearchParams();
  if (opts?.origin) params.set("origin", opts.origin);
  if (opts?.category) params.set("category", opts.category);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories${qs ? `?${qs}` : ""}`);
}

export async function deleteAllAutoProjectMemories(
  projectId: string,
): Promise<{ deleted: number }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
    method: "DELETE",
  });
}

export async function exportProjectMemories(
  projectId: string,
): Promise<{ memories: ProjectMemory[]; total: number }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories/export`);
}

export async function createProjectMemory(
  projectId: string,
  content: string,
): Promise<ProjectMemory> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
    method: "POST",
    body: JSON.stringify({ content, sourceType: "manual" }),
  });
}

export async function updateProjectMemory(
  projectId: string,
  memoryId: string,
  body: { content?: string; enabled?: boolean },
): Promise<ProjectMemory> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteProjectMemory(
  projectId: string,
  memoryId: string,
): Promise<{ deleted: boolean }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  });
}

export async function listMemoryGrants(
  projectId: string,
): Promise<{ grants: MemoryGrant[] }> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memory-grants`);
}

export async function createMemoryGrant(
  projectId: string,
  sourceProjectId: string,
): Promise<MemoryGrant> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/memory-grants`, {
    method: "POST",
    body: JSON.stringify({ sourceProjectId }),
  });
}

export async function revokeMemoryGrant(
  projectId: string,
  sourceProjectId: string,
): Promise<{ revoked: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/memory-grants/${encodeURIComponent(sourceProjectId)}`,
    { method: "DELETE" },
  );
}

export type ProjectMediaKind = "image" | "video" | "document" | "other";

export type ProjectMediaItem = {
  id: number;
  projectId: string;
  uploadedByUserId?: number | null;
  kind: ProjectMediaKind;
  mimeType: string;
  fileName: string;
  sizeBytes: number;
  sourceModel?: string | null;
  sourcePrompt?: string | null;
  chatSessionId?: string | null;
  contentHash?: string | null;
  storagePath: string;
  url: string;
  createdAt?: string | null;
  expiresAt?: string | null;
};

/** sessionStorage key for queuing a project media file into the next chat turn. */
export const PROJECT_MEDIA_ATTACH_KEY = "alphaRouter.projectMediaAttach";
export const PROJECT_MEDIA_ATTACH_EVENT = "alpharouter:project-media-attach";
export const PROJECT_MEDIA_ATTACH_CONSUMED_EVENT = "alpharouter:project-media-attach-consumed";

export type ProjectMediaAttachPayload = {
  projectId: string;
  mediaId: number;
  url: string;
  fileName: string;
  mimeType: string;
  kind?: ProjectMediaKind;
};

export function queueProjectMediaForChat(
  item: Pick<ProjectMediaItem, "id" | "url" | "fileName" | "mimeType" | "kind">,
  projectId: string,
): ProjectMediaAttachPayload {
  const payload: ProjectMediaAttachPayload = {
    projectId,
    mediaId: item.id,
    url: item.url,
    fileName: item.fileName,
    mimeType: item.mimeType,
    kind: item.kind,
  };
  try {
    sessionStorage.setItem(PROJECT_MEDIA_ATTACH_KEY, JSON.stringify(payload));
  } catch {
    /* quota / private mode */
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PROJECT_MEDIA_ATTACH_EVENT));
  }
  return payload;
}

export function readQueuedProjectMediaAttach(): ProjectMediaAttachPayload | null {
  try {
    const raw = sessionStorage.getItem(PROJECT_MEDIA_ATTACH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ProjectMediaAttachPayload;
    if (!parsed?.projectId || typeof parsed.url !== "string" || !parsed.url) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearQueuedProjectMediaAttach(): void {
  try {
    sessionStorage.removeItem(PROJECT_MEDIA_ATTACH_KEY);
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PROJECT_MEDIA_ATTACH_CONSUMED_EVENT));
  }
}

export async function listProjectMedia(
  projectId: string,
  opts?: { kind?: string; q?: string; limit?: number; offset?: number },
): Promise<{ items: ProjectMediaItem[]; total: number }> {
  const params = new URLSearchParams();
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.q) params.set("q", opts.q);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return api(`/api/projects/${encodeURIComponent(projectId)}/media${qs ? `?${qs}` : ""}`);
}

export async function uploadProjectMedia(
  projectId: string,
  file: File,
): Promise<ProjectMediaItem> {
  const form = new FormData();
  form.append("file", file);
  return api(`/api/projects/${encodeURIComponent(projectId)}/media`, {
    method: "POST",
    body: form,
  });
}

export async function getProjectMedia(
  projectId: string,
  mediaId: number,
): Promise<ProjectMediaItem> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}`,
  );
}

export function projectMediaDownloadUrl(projectId: string, mediaId: number): string {
  return `/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}/download`;
}

export type ProjectChatSession = {
  id: string;
  title: string;
  model: string;
  messageCount: number;
  revision: number;
  pinned: boolean;
  createdByUserId?: number | null;
  createdAt?: number | string | null;
  updatedAt?: number | string | null;
  lastMessageAt?: number | string | null;
};

export async function listProjectChats(
  projectId: string,
  opts?: { limit?: number; offset?: number; q?: string },
): Promise<{
  sessions: Record<string, unknown>[];
  total: number;
  pinnedSessionIds: string[];
  lastOpenedSessionId?: string | null;
}> {
  const params = new URLSearchParams();
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  if (opts?.q?.trim()) params.set("q", opts.q.trim());
  const qs = params.toString();
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats${qs ? `?${qs}` : ""}`,
  );
}

export async function getProjectChat(
  projectId: string,
  sessionId: string,
): Promise<Record<string, unknown>> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}`,
  );
}

export async function syncProjectChats(
  projectId: string,
  opts?: { since?: number; sessionId?: string | null; afterSequence?: number | null },
): Promise<{
  serverTimeMs: number;
  aclVersion?: number;
  total: number;
  pinnedSessionIds: string[];
  sessionIds: string[];
  sessions: Record<string, unknown>[];
  messages?: Record<string, unknown>[];
  messageSessionId?: string | null;
  completeWindow?: boolean;
  goneSessionId?: string | null;
  lastOpenedSessionId?: string | null;
}> {
  const params = new URLSearchParams();
  if (opts?.since != null) params.set("since", String(opts.since));
  if (opts?.sessionId) params.set("session_id", opts.sessionId);
  if (opts?.afterSequence != null) params.set("after_sequence", String(opts.afterSequence));
  const qs = params.toString();
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats/sync${qs ? `?${qs}` : ""}`,
  );
}

export async function createProjectChat(
  projectId: string,
  body: { id?: string; title?: string; model?: string },
): Promise<ProjectChatSession> {
  return api(`/api/projects/${encodeURIComponent(projectId)}/chats`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteProjectChat(
  projectId: string,
  sessionId: string,
): Promise<{ deleted: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

export async function pinProjectChat(
  projectId: string,
  sessionId: string,
): Promise<{ sessionId: string; pinned: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/pin`,
    { method: "POST" },
  );
}

export async function unpinProjectChat(
  projectId: string,
  sessionId: string,
): Promise<{ sessionId: string; pinned: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/pin`,
    { method: "DELETE" },
  );
}

export async function deleteProjectMedia(
  projectId: string,
  mediaId: number,
): Promise<{ deleted: boolean }> {
  return api(
    `/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}`,
    { method: "DELETE" },
  );
}
