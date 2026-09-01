import { api } from "../api";
import { normalizeProjectChatComposerPrefs, } from "./projectChatComposer";
export function isProjectOwnerRole(role) {
    return role === "primary_owner" || role === "owner";
}
export function isPrimaryOwnerRole(role) {
    return role === "primary_owner";
}
export function projectRoleLabel(role) {
    if (role === "primary_owner")
        return "Primary Owner";
    if (role === "owner")
        return "Owner";
    if (role === "contributor")
        return "Contributor";
    if (role === "viewer")
        return "Viewer";
    return role ?? "";
}
export function assignableProjectRoles(actorRole) {
    if (actorRole === "primary_owner")
        return ["owner", "contributor", "viewer"];
    if (actorRole === "owner")
        return ["contributor", "viewer"];
    return [];
}
export function needsPublicTypedConfirm(current, next) {
    return current !== "public" && next === "public";
}
export const MAX_PROJECT_RESOURCE_UPLOAD_FILES = 20;
export function projectResourceKnowledgeStatus(resource) {
    return (resource.versionStatus || resource.documentStatus || resource.status || "").trim();
}
export const PROJECT_RESOURCE_WAITING_LABEL = "Waiting for Admin Approval";
/** User-facing resource status: hide KB pipeline until the file is Published. */
export function projectResourceUserStatus(resource) {
    const kb = projectResourceKnowledgeStatus(resource).toLowerCase();
    if (kb === "published")
        return "Published";
    if (kb === "failed")
        return "Failed";
    if (kb === "revoked")
        return "Revoked";
    return PROJECT_RESOURCE_WAITING_LABEL;
}
export function projectResourceUserStatusTone(resource) {
    const kb = projectResourceKnowledgeStatus(resource).toLowerCase();
    if (kb === "published")
        return "published";
    if (kb === "failed" || kb === "revoked")
        return kb;
    return "review";
}
export function projectResourceTooManyFilesMessage(selectedCount) {
    return (`You can upload at most ${MAX_PROJECT_RESOURCE_UPLOAD_FILES} files at a time. ` +
        `You selected ${selectedCount}. Please choose ${MAX_PROJECT_RESOURCE_UPLOAD_FILES} or fewer and try again.`);
}
export async function listProjects(scope = "mine", opts) {
    const params = new URLSearchParams({ scope });
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset != null)
        params.set("offset", String(opts.offset));
    if (opts?.q)
        params.set("q", opts.q);
    return api(`/api/projects?${params.toString()}`);
}
export async function createProject(body) {
    return api("/api/projects", { method: "POST", body: JSON.stringify(body) });
}
export async function getProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}`);
}
export async function getProjectOverview(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/overview`);
}
export async function putProjectPrefs(projectId, body) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/prefs`, {
        method: "PUT",
        body: JSON.stringify(body),
    });
}
export async function getProjectChatComposerPrefs(projectId, sessionId) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/composer-prefs`);
    return normalizeProjectChatComposerPrefs(data);
}
export async function putProjectChatComposerPrefs(projectId, sessionId, body) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/composer-prefs`, { method: "PUT", body: JSON.stringify(body) });
    return normalizeProjectChatComposerPrefs(data);
}
export async function updateProject(projectId, body) {
    return api(`/api/projects/${encodeURIComponent(projectId)}`, {
        method: "PUT",
        body: JSON.stringify(body),
    });
}
export async function deleteProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}
export async function archiveProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/archive`, { method: "POST" });
}
export async function restoreProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/restore`, { method: "POST" });
}
export async function purgeProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/purge`, { method: "POST" });
}
export async function leaveProject(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/leave`, { method: "POST" });
}
export async function listMembers(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/members`);
}
export async function addMember(projectId, userId, role = "viewer") {
    return api(`/api/projects/${encodeURIComponent(projectId)}/members`, {
        method: "POST",
        body: JSON.stringify({ userId, role }),
    });
}
export async function updateMemberRole(projectId, userId, role) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
    });
}
export async function removeMember(projectId, userId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/members/${userId}`, {
        method: "DELETE",
    });
}
export async function listInvitableUsers(projectId, q, limit) {
    const params = new URLSearchParams();
    if (q)
        params.set("q", q);
    if (limit != null)
        params.set("limit", String(limit));
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/invitable-users${qs ? `?${qs}` : ""}`);
}
export async function listInvitations(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/invitations`);
}
export async function createInvitation(body) {
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
export async function revokeInvitation(projectId, invitationId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/invitations/${encodeURIComponent(invitationId)}`, { method: "DELETE" });
}
export async function claimInvitation(token) {
    return api("/api/projects/invitations/claim", {
        method: "POST",
        body: JSON.stringify({ token }),
    });
}
export async function getProjectConfig(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/config`);
}
export async function updateProjectConfig(projectId, body) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/config`, {
        method: "PUT",
        body: JSON.stringify(body),
    });
}
export async function listProjectConfigVersions(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/config/versions`);
}
export function groundingTogglesFromPolicy(policy) {
    const src = policy ?? {};
    return {
        useProjectResources: src.useProjectResources !== false,
        useGrantedMemory: src.useGrantedMemory !== false,
    };
}
export function groundingPolicyFromToggles(opts) {
    return {
        useProjectResources: opts.useProjectResources,
        useGrantedMemory: opts.useGrantedMemory,
    };
}
export async function listProjectResources(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.status)
        params.set("status", opts.status);
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset != null)
        params.set("offset", String(opts.offset));
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/resources${qs ? `?${qs}` : ""}`);
}
export async function uploadProjectResource(projectId, file, title) {
    const form = new FormData();
    form.append("file", file);
    if (title)
        form.append("title", title);
    return api(`/api/projects/${encodeURIComponent(projectId)}/resources`, {
        method: "POST",
        body: form,
    });
}
export async function deleteProjectResource(projectId, resourceId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/resources/${encodeURIComponent(resourceId)}`, {
        method: "DELETE",
    });
}
export async function listProjectMemories(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.origin)
        params.set("origin", opts.origin);
    if (opts?.category)
        params.set("category", opts.category);
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset != null)
        params.set("offset", String(opts.offset));
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories${qs ? `?${qs}` : ""}`);
}
export async function deleteAllAutoProjectMemories(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
        method: "DELETE",
    });
}
export async function exportProjectMemories(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories/export`);
}
export async function createProjectMemory(projectId, content) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
        method: "POST",
        body: JSON.stringify({ content, sourceType: "manual" }),
    });
}
export async function updateProjectMemory(projectId, memoryId, body) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
    });
}
export async function deleteProjectMemory(projectId, memoryId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`, {
        method: "DELETE",
    });
}
export async function listMemoryGrants(projectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memory-grants`);
}
export async function createMemoryGrant(projectId, sourceProjectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memory-grants`, {
        method: "POST",
        body: JSON.stringify({ sourceProjectId }),
    });
}
export async function revokeMemoryGrant(projectId, sourceProjectId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/memory-grants/${encodeURIComponent(sourceProjectId)}`, { method: "DELETE" });
}
/** sessionStorage key for queuing a project media file into the next chat turn. */
export const PROJECT_MEDIA_ATTACH_KEY = "alphaRouter.projectMediaAttach";
export const PROJECT_MEDIA_ATTACH_EVENT = "alpharouter:project-media-attach";
export const PROJECT_MEDIA_ATTACH_CONSUMED_EVENT = "alpharouter:project-media-attach-consumed";
export function queueProjectMediaForChat(item, projectId) {
    const payload = {
        projectId,
        mediaId: item.id,
        url: item.url,
        fileName: item.fileName,
        mimeType: item.mimeType,
        kind: item.kind,
    };
    try {
        sessionStorage.setItem(PROJECT_MEDIA_ATTACH_KEY, JSON.stringify(payload));
    }
    catch {
        /* quota / private mode */
    }
    if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(PROJECT_MEDIA_ATTACH_EVENT));
    }
    return payload;
}
export function readQueuedProjectMediaAttach() {
    try {
        const raw = sessionStorage.getItem(PROJECT_MEDIA_ATTACH_KEY);
        if (!raw)
            return null;
        const parsed = JSON.parse(raw);
        if (!parsed?.projectId || typeof parsed.url !== "string" || !parsed.url)
            return null;
        return parsed;
    }
    catch {
        return null;
    }
}
export function clearQueuedProjectMediaAttach() {
    try {
        sessionStorage.removeItem(PROJECT_MEDIA_ATTACH_KEY);
    }
    catch {
        /* ignore */
    }
    if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(PROJECT_MEDIA_ATTACH_CONSUMED_EVENT));
    }
}
export async function listProjectMedia(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.kind)
        params.set("kind", opts.kind);
    if (opts?.q)
        params.set("q", opts.q);
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset != null)
        params.set("offset", String(opts.offset));
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/media${qs ? `?${qs}` : ""}`);
}
export async function uploadProjectMedia(projectId, file) {
    const form = new FormData();
    form.append("file", file);
    return api(`/api/projects/${encodeURIComponent(projectId)}/media`, {
        method: "POST",
        body: form,
    });
}
export async function getProjectMedia(projectId, mediaId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}`);
}
export function projectMediaDownloadUrl(projectId, mediaId) {
    return `/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}/download`;
}
export async function listProjectChats(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset)
        params.set("offset", String(opts.offset));
    if (opts?.q?.trim())
        params.set("q", opts.q.trim());
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats${qs ? `?${qs}` : ""}`);
}
export async function getProjectChat(projectId, sessionId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}`);
}
export async function syncProjectChats(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.since != null)
        params.set("since", String(opts.since));
    if (opts?.sessionId)
        params.set("session_id", opts.sessionId);
    if (opts?.afterSequence != null)
        params.set("after_sequence", String(opts.afterSequence));
    const qs = params.toString();
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats/sync${qs ? `?${qs}` : ""}`);
}
export async function createProjectChat(projectId, body) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats`, {
        method: "POST",
        body: JSON.stringify(body),
    });
}
export async function deleteProjectChat(projectId, sessionId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}
export async function pinProjectChat(projectId, sessionId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/pin`, { method: "POST" });
}
export async function unpinProjectChat(projectId, sessionId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(sessionId)}/pin`, { method: "DELETE" });
}
export async function deleteProjectMedia(projectId, mediaId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(String(mediaId))}`, { method: "DELETE" });
}
