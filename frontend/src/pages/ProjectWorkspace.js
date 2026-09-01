import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { formatApiError, getCachedSession } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import Modal from "../components/Modal";
import RowActionsMenu from "../components/RowActionsMenu";
import ChatPanel from "../components/ChatPanel";
import ProjectRooms from "./ProjectRooms";
import ActivityView from "../components/activity/ActivityView";
import { formatRequests, formatSpend, formatTokens } from "../components/activity/formatters";
import { USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
import { addMember, archiveProject, createInvitation, createMemoryGrant, createProjectMemory, deleteAllAutoProjectMemories, deleteProject, deleteProjectMedia, deleteProjectMemory, deleteProjectResource, getProject, getProjectConfig, getProjectOverview, groundingPolicyFromToggles, groundingTogglesFromPolicy, leaveProject, listInvitableUsers, listInvitations, listMembers, listMemoryGrants, listProjectConfigVersions, listProjectMedia, listProjectMemories, listProjectResources, listProjects, MAX_PROJECT_RESOURCE_UPLOAD_FILES, needsPublicTypedConfirm, PROJECT_MEDIA_ATTACH_CONSUMED_EVENT, PROJECT_MEDIA_ATTACH_EVENT, assignableProjectRoles, isPrimaryOwnerRole, isProjectOwnerRole, projectRoleLabel, projectResourceUserStatus, projectResourceUserStatusTone, projectResourceTooManyFilesMessage, purgeProject, queueProjectMediaForChat, readQueuedProjectMediaAttach, removeMember, restoreProject, revokeInvitation, revokeMemoryGrant, updateMemberRole, updateProject, updateProjectConfig, updateProjectMemory, uploadProjectMedia, uploadProjectResource, } from "../lib/projectsApi";
import { useConfirm } from "../context/ConfirmContext";
import { agentStatusTone } from "../lib/agentPlatform";
import { formatLocalDate, formatLocalDateTime } from "../lib/dateTime";
const MEDIA_KIND_FILTERS = [
    { id: "", label: "All" },
    { id: "image", label: "Images" },
    { id: "video", label: "Videos" },
    { id: "document", label: "Documents" },
    { id: "other", label: "Other" },
];
const MEMORY_PAGE_SIZE = 100;
const MEMORY_ORIGIN_FILTERS = [
    { id: "", label: "All" },
    { id: "manual", label: "Manual" },
    { id: "auto", label: "Learned" },
];
export default function ProjectWorkspacePage() {
    const { projectId = "" } = useParams();
    const location = useLocation();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [tab, setTab] = useState("chats");
    const [pendingMedia, setPendingMedia] = useState(null);
    const projectsListTo = location.pathname.startsWith("/admin")
        ? "/admin/projects"
        : "/app/projects";
    const loadProject = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const p = await getProject(projectId);
            setProject(p);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, [projectId]);
    useEffect(() => {
        void loadProject();
    }, [loadProject]);
    useEffect(() => {
        if (searchParams.get("session"))
            setTab("chats");
    }, [searchParams]);
    useEffect(() => {
        setPendingMedia(readQueuedProjectMediaAttach());
        const onQueued = () => setPendingMedia(readQueuedProjectMediaAttach());
        const onConsumed = () => setPendingMedia(null);
        window.addEventListener(PROJECT_MEDIA_ATTACH_EVENT, onQueued);
        window.addEventListener(PROJECT_MEDIA_ATTACH_CONSUMED_EVENT, onConsumed);
        return () => {
            window.removeEventListener(PROJECT_MEDIA_ATTACH_EVENT, onQueued);
            window.removeEventListener(PROJECT_MEDIA_ATTACH_CONSUMED_EVENT, onConsumed);
        };
    }, [tab]);
    const canEdit = isProjectOwnerRole(project?.myRole);
    const canLifecycle = isPrimaryOwnerRole(project?.myRole);
    const canManageMembers = canEdit;
    const canUpload = isProjectOwnerRole(project?.myRole) || project?.myRole === "contributor";
    const projectReadOnly = Boolean(project && (project.myRole === "viewer" || !project.isMember));
    const roleLabel = projectRoleLabel(project?.myRole);
    useEffect(() => {
        if (tab === "activity" && !canEdit)
            setTab("chats");
        if (tab === "rooms" && project && !project.isMember)
            setTab("chats");
    }, [tab, canEdit, project]);
    const conversationTabs = project?.isMember ? ["chats", "rooms"] : ["chats"];
    const tabs = canEdit
        ? [...conversationTabs, "resources", "media", "overview", "activity", "members", "settings"]
        : [...conversationTabs, "resources", "media", "overview", "members", "settings"];
    const tabContent = !project || tab === "chats"
        ? null
        : tab === "rooms"
            ? (_jsx(ProjectRooms, { projectId: project.id, canWrite: canUpload, onHandoff: (targetSessionId) => {
                    navigate(`?session=${encodeURIComponent(targetSessionId)}`);
                    setTab("chats");
                } }))
            : tab === "overview"
                ? (_jsx(OverviewTab, { project: project, onSelectTab: setTab, canOpenActivity: canEdit }))
                : tab === "activity" && canEdit
                    ? (_jsx(ActivityView, { scope: "project", projectId: project.id, title: USAGE_AND_ACTIVITY_LABEL }))
                    : tab === "resources"
                        ? _jsx(ResourcesTab, { projectId: project.id, canUpload: canUpload })
                        : tab === "media"
                            ? (_jsx(MediaTab, { projectId: project.id, myRole: project.myRole ?? null, canUpload: canUpload, onUseInChat: () => setTab("chats") }))
                            : tab === "settings"
                                ? _jsx(SettingsTab, { projectId: project.id, canEdit: canEdit })
                                : (_jsx(MembersTab, { projectId: project.id, canManageMembers: canManageMembers, myRole: project.myRole ?? null }));
    return (_jsx(ChatPanel, { projectId: projectId, projectReadOnly: projectReadOnly, enableModelChrome: tab === "chats", hideChatSidebar: tab === "rooms", onProjectChatFocus: () => setTab("chats"), projectSidebarHeader: _jsxs("div", { className: "alpha-router-project-identity", children: [_jsx(Link, { to: projectsListTo, className: "alpha-router-project-identity__back", children: "\u2190 Projects" }), _jsx("div", { className: "alpha-router-project-identity__name", children: project?.name ?? "Project" }), _jsxs("div", { className: "alpha-router-project-identity__meta", children: [_jsx("span", { children: "Shared project chat" }), roleLabel ? _jsx("span", { className: "project-role-chip", children: roleLabel }) : null] })] }), projectToolbar: _jsxs("div", { className: "project-chat-toolbar", children: [_jsxs("div", { className: "project-chat-toolbar__row", children: [_jsxs("div", { className: "project-chat-toolbar__title", children: [tab === "rooms" ? (_jsx(Link, { to: projectsListTo, className: "project-chat-toolbar__back", children: "\u2190 Projects" })) : null, _jsx("h1", { children: project?.name ?? "Project" }), roleLabel ? _jsx("span", { className: "project-role-chip project-role-chip--light", children: roleLabel }) : null] }), project ? (_jsx(ProjectActionsMenu, { project: project, canEdit: canEdit, canLifecycle: canLifecycle, onChanged: loadProject, onDeleted: () => navigate(projectsListTo) })) : null] }), _jsx("nav", { className: "project-tabs", "aria-label": "Project sections", children: tabs.map((t) => (_jsx("button", { type: "button", className: `project-tab${tab === t ? " project-tab--active" : ""}`, onClick: () => setTab(t), children: t.charAt(0).toUpperCase() + t.slice(1) }, t))) }), error ? _jsx("div", { className: "flash flash-error", children: error }) : null, project?.status === "archived" ? (_jsx("div", { className: "flash", children: "This project is archived. Restore it from the menu to show it in Explore again." })) : null, project?.status === "deletion_pending" ? (_jsx("div", { className: "flash flash-error", children: "This project is pending deletion. The Primary Owner can purge it now, or the nightly job will remove it after the retention period." })) : null, loading && !project ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null] }), projectBanner: tab === "chats" ? (_jsxs(_Fragment, { children: [pendingMedia ? (_jsxs("div", { className: "flash", children: ["Queued for the next chat message: ", _jsx("strong", { children: pendingMedia.fileName })] })) : null, projectReadOnly && project ? (_jsx("p", { className: "form-hint project-chat-readonly-hint", children: "You can read project chats. Only Owners and Contributors can send messages." })) : null] })) : null, mainOverride: tabContent }));
}
function ProjectActionsMenu({ project, canEdit, canLifecycle, onChanged, onDeleted, }) {
    const [editOpen, setEditOpen] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [confirmLeave, setConfirmLeave] = useState(false);
    const [confirmArchive, setConfirmArchive] = useState(false);
    const [confirmPurge, setConfirmPurge] = useState(false);
    const [confirmPublic, setConfirmPublic] = useState(false);
    const [name, setName] = useState(project.name);
    const [description, setDescription] = useState(project.description ?? "");
    const [visibility, setVisibility] = useState(project.visibility);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState("");
    async function saveEdit() {
        if (needsPublicTypedConfirm(project.visibility, visibility)) {
            setConfirmPublic(true);
            return;
        }
        await commitEdit();
    }
    async function commitEdit() {
        setBusy(true);
        setErr("");
        try {
            await updateProject(project.id, {
                name: name.trim(),
                description: description.trim() || null,
                visibility,
            });
            setEditOpen(false);
            setConfirmPublic(false);
            onChanged();
        }
        catch (e) {
            setErr(formatApiError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function doDelete() {
        setBusy(true);
        try {
            await deleteProject(project.id);
            onDeleted();
        }
        catch (e) {
            setErr(formatApiError(e));
            setBusy(false);
        }
    }
    async function doLeave() {
        setBusy(true);
        try {
            await leaveProject(project.id);
            onDeleted();
        }
        catch (e) {
            setErr(formatApiError(e));
            setBusy(false);
        }
    }
    async function doArchive() {
        setBusy(true);
        setErr("");
        try {
            await archiveProject(project.id);
            setConfirmArchive(false);
            onChanged();
        }
        catch (e) {
            setErr(formatApiError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function doRestore() {
        setBusy(true);
        setErr("");
        try {
            await restoreProject(project.id);
            onChanged();
        }
        catch (e) {
            setErr(formatApiError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function doPurge() {
        setBusy(true);
        try {
            await purgeProject(project.id);
            onDeleted();
        }
        catch (e) {
            setErr(formatApiError(e));
            setBusy(false);
        }
    }
    const actions = [];
    if (canEdit) {
        actions.push({
            label: "Edit",
            onClick: () => {
                setName(project.name);
                setDescription(project.description ?? "");
                setVisibility(project.visibility);
                setErr("");
                setEditOpen(true);
            },
        });
    }
    if (canLifecycle) {
        if (project.status === "active") {
            actions.push({ label: "Archive", onClick: () => setConfirmArchive(true) });
        }
        if (project.status === "archived") {
            actions.push({ label: "Restore", onClick: () => void doRestore() });
        }
        if (project.status === "deletion_pending") {
            actions.push({
                label: "Purge now",
                danger: true,
                onClick: () => setConfirmPurge(true),
            });
        }
        else {
            actions.push({
                label: "Delete",
                danger: true,
                onClick: () => setConfirmDelete(true),
            });
        }
    }
    if (!isPrimaryOwnerRole(project.myRole)) {
        actions.push({ label: "Leave project", onClick: () => setConfirmLeave(true) });
    }
    if (actions.length === 0)
        return null;
    return (_jsxs(_Fragment, { children: [_jsx(RowActionsMenu, { actions: actions }), _jsx(Modal, { open: editOpen, title: "Edit project", onClose: () => setEditOpen(false), panelClassName: "modal-panel--project-form", children: _jsxs("form", { onSubmit: (e) => {
                        e.preventDefault();
                        void saveEdit();
                    }, children: [_jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Name" }), _jsx("input", { type: "text", value: name, onChange: (e) => setName(e.target.value), maxLength: 255, required: true, autoFocus: true })] }), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Description" }), _jsx("textarea", { value: description, onChange: (e) => setDescription(e.target.value), maxLength: 4000, rows: 3 })] }), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Visibility" }), _jsxs("select", { value: visibility, onChange: (e) => setVisibility(e.target.value), children: [_jsx("option", { value: "private", children: "Private (members only)" }), _jsx("option", { value: "public", children: "Public (all authenticated users)" })] })] }), visibility === "public" && project.visibility !== "public" ? (_jsx("p", { className: "form-hint form-hint--warning", children: "Making this project public grants read access to every authenticated user. Only do this if all resources and chat content are safe to share organization-wide." })) : null, err ? _jsx("p", { className: "form-error", children: err }) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn btn-primary", disabled: busy || !name.trim(), children: busy ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setEditOpen(false), children: "Cancel" })] })] }) }), _jsx(ConfirmModal, { open: confirmPublic, title: "Make this project public", message: "Type PUBLIC to confirm. Every authenticated user will be able to read this project's chats, resources, and media.", danger: true, confirmLabel: "Make public", cancelLabel: "Cancel", promptLabel: "Type PUBLIC to confirm", promptExactMatch: "PUBLIC", onConfirm: () => void commitEdit(), onCancel: () => setConfirmPublic(false) }), _jsx(ConfirmModal, { open: confirmDelete, title: "Delete project", message: `This marks “${project.name}” for deletion. Members keep access until an Owner purges it or the retention job removes it.`, danger: true, confirmLabel: "Mark for deletion", cancelLabel: "Cancel", promptLabel: "Type the project name to confirm", promptExactMatch: project.name, onConfirm: () => void doDelete(), onCancel: () => setConfirmDelete(false) }), _jsx(ConfirmModal, { open: confirmArchive, title: "Archive project", message: `“${project.name}” will leave Explore. Members can still open it from My projects until you restore it.`, confirmLabel: "Archive", cancelLabel: "Cancel", onConfirm: () => void doArchive(), onCancel: () => setConfirmArchive(false) }), _jsx(ConfirmModal, { open: confirmPurge, title: "Purge project", message: `Permanently delete “${project.name}”, including chats, resources, and project media. This cannot be undone.`, danger: true, confirmLabel: "Purge permanently", cancelLabel: "Cancel", promptLabel: "Type the project name to confirm", promptExactMatch: project.name, onConfirm: () => void doPurge(), onCancel: () => setConfirmPurge(false) }), _jsx(ConfirmModal, { open: confirmLeave, title: "Leave project", message: "You will no longer have access to this project. An Owner can re-invite you later.", confirmLabel: "Leave", cancelLabel: "Cancel", onConfirm: () => void doLeave(), onCancel: () => setConfirmLeave(false) })] }));
}
function projectVisibilityLabel(visibility) {
    return visibility === "public" ? "Public" : "Private";
}
function projectOverviewStatusLabel(status) {
    if (status === "archived")
        return "Archived";
    if (status === "deletion_pending")
        return "Pending deletion";
    return "Active";
}
function OverviewStatCard({ title, value, onOpen, }) {
    const inner = (_jsxs(_Fragment, { children: [_jsx("p", { className: "overview-kpi-card__title", children: title }), _jsx("p", { className: "overview-kpi-card__value", children: value })] }));
    if (onOpen) {
        return (_jsx("button", { type: "button", className: "overview-kpi-card card project-overview-kpi-btn", onClick: onOpen, children: inner }));
    }
    return _jsx("article", { className: "overview-kpi-card card", children: inner });
}
function OverviewTab({ project, onSelectTab, canOpenActivity, }) {
    const [overview, setOverview] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError("");
        void getProjectOverview(project.id)
            .then((data) => {
            if (!cancelled)
                setOverview(data);
        })
            .catch((err) => {
            if (!cancelled)
                setError(formatApiError(err));
        })
            .finally(() => {
            if (!cancelled)
                setLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, [project.id]);
    const counts = overview?.counts;
    const usage = overview?.usage;
    const roleLabel = projectRoleLabel(project.myRole);
    const createdLabel = formatLocalDate(project.createdAt);
    const createdTitle = formatLocalDateTime(project.createdAt);
    const countValue = (n) => counts ? String(n ?? 0) : loading ? "…" : "—";
    return (_jsxs("div", { className: "project-overview", children: [_jsxs("section", { className: "project-overview-identity card", children: [project.description ? (_jsx("p", { className: "project-overview-identity__desc", children: project.description })) : (_jsx("p", { className: "project-overview-identity__desc project-overview-identity__desc--empty", children: "No description yet" })), _jsxs("div", { className: "project-overview-identity__meta", children: [_jsx("span", { className: `project-card-badge project-card-badge--${project.visibility}`, children: projectVisibilityLabel(project.visibility) }), _jsx("span", { className: `project-card-badge project-card-badge--${project.status}`, children: projectOverviewStatusLabel(project.status) }), roleLabel ? (_jsx("span", { className: "project-role-chip project-role-chip--light", children: roleLabel })) : null, createdLabel !== "—" ? (_jsxs("span", { className: "project-overview-identity__created", title: createdTitle, children: ["Created ", createdLabel] })) : null] })] }), _jsxs("div", { className: "overview-kpi-row", children: [_jsx(OverviewStatCard, { title: "Members", value: countValue(counts?.members), onOpen: () => onSelectTab("members") }), _jsx(OverviewStatCard, { title: "Chats", value: countValue(counts?.chats), onOpen: () => onSelectTab("chats") }), _jsx(OverviewStatCard, { title: "Resources", value: countValue(counts?.resources), onOpen: () => onSelectTab("resources") }), _jsx(OverviewStatCard, { title: "Media", value: countValue(counts?.media), onOpen: () => onSelectTab("media") })] }), canOpenActivity && (usage || loading) ? (_jsxs("section", { className: "project-overview-usage card", children: [_jsxs("header", { className: "overview-card-head", children: [_jsxs("h3", { children: ["Last ", usage?.windowDays ?? 30, " days"] }), _jsx("button", { type: "button", className: "overview-explore-link", onClick: () => onSelectTab("activity"), children: "Open Activity \u2192" })] }), _jsxs("div", { className: "overview-kpi-row", children: [_jsx(OverviewStatCard, { title: "Spend", value: usage ? formatSpend(usage.totalCostUsd) : "…" }), _jsx(OverviewStatCard, { title: "Media spend", value: usage ? formatSpend(usage.mediaCostUsd) : "…" }), _jsx(OverviewStatCard, { title: "Requests", value: usage ? formatRequests(usage.requests) : "…" }), _jsx(OverviewStatCard, { title: "Tokens", value: usage ? formatTokens(usage.totalTokens) : "…" })] })] })) : null, error ? _jsx("p", { className: "form-error", children: error }) : null] }));
}
function ResourcesTab({ projectId, canUpload }) {
    const [resources, setResources] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [files, setFiles] = useState([]);
    const [title, setTitle] = useState("");
    const [uploadProgress, setUploadProgress] = useState(null);
    const fileInput = useRef(null);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const res = await listProjectResources(projectId, { limit: 100 });
            setResources(res.resources);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, [projectId]);
    useEffect(() => {
        void load();
    }, [load]);
    function resetUploadForm() {
        setFiles([]);
        setTitle("");
        if (fileInput.current)
            fileInput.current.value = "";
    }
    function onUploadFilesChange(list) {
        const selected = Array.from(list || []);
        if (selected.length > MAX_PROJECT_RESOURCE_UPLOAD_FILES) {
            resetUploadForm();
            setError(projectResourceTooManyFilesMessage(selected.length));
            return;
        }
        setError("");
        setFiles(selected);
        if (selected.length !== 1)
            setTitle("");
    }
    async function upload() {
        if (files.length === 0)
            return;
        if (files.length > MAX_PROJECT_RESOURCE_UPLOAD_FILES) {
            setError(projectResourceTooManyFilesMessage(files.length));
            return;
        }
        setBusy(true);
        setError("");
        const failures = [];
        setUploadProgress({ current: 0, total: files.length });
        try {
            for (const [index, file] of files.entries()) {
                setUploadProgress({ current: index + 1, total: files.length });
                try {
                    await uploadProjectResource(projectId, file, files.length === 1 ? title.trim() || undefined : undefined);
                }
                catch (err) {
                    failures.push(`${file.name}: ${formatApiError(err)}`);
                }
            }
            resetUploadForm();
            await load();
            if (failures.length)
                setError(failures.join(" "));
        }
        finally {
            setBusy(false);
            setUploadProgress(null);
        }
    }
    async function remove(id) {
        try {
            await deleteProjectResource(projectId, id);
            setResources((prev) => prev.filter((r) => r.id !== id));
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    return (_jsxs("div", { className: "project-tab-body", children: [canUpload ? (_jsxs("div", { className: "project-upload", children: [_jsx("h3", { children: "Upload resource" }), _jsx("input", { ref: fileInput, type: "file", multiple: true, onChange: (e) => onUploadFilesChange(e.target.files), disabled: busy }), files.length <= 1 ? (_jsx("input", { type: "text", placeholder: "Title (optional)", value: title, onChange: (e) => setTitle(e.target.value), className: "input", disabled: busy })) : (_jsxs("p", { className: "muted-text", children: [files.length, " files selected. Titles will use each file name."] })), _jsx("button", { type: "button", className: "btn btn-primary", disabled: files.length === 0 || busy, onClick: () => void upload(), children: uploadProgress
                            ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}…`
                            : files.length > 1
                                ? `Upload ${files.length} files`
                                : "Upload" }), _jsxs("p", { className: "muted-text", children: ["Up to ", MAX_PROJECT_RESOURCE_UPLOAD_FILES, " files per upload. An optional title is available only when uploading a single file."] })] })) : null, error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Title" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Uploaded" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [resources.map((r) => {
                                const statusLabel = projectResourceUserStatus(r);
                                return (_jsxs("tr", { children: [_jsxs("td", { children: [r.title, r.failureReason ? (_jsx("small", { className: "agent-table-sub error", style: { display: "block" }, children: r.failureReason })) : null] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(projectResourceUserStatusTone(r))}`, children: statusLabel }) }), _jsx("td", { children: r.createdAt ?? "—" }), _jsx("td", { children: canUpload ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void remove(r.id), children: "Remove" })) : null })] }, r.id));
                            }), resources.length === 0 && !loading ? (_jsx("tr", { children: _jsx("td", { colSpan: 4, className: "empty-state", children: "No resources yet." }) })) : null] })] })] }));
}
function formatMediaBytes(n) {
    if (n < 1024)
        return `${n} B`;
    if (n < 1024 * 1024)
        return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
function formatMediaDate(value) {
    if (!value)
        return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime()))
        return value;
    return d.toLocaleString();
}
function queueMediaForChat(item, projectId) {
    queueProjectMediaForChat(item, projectId);
}
function MediaTab({ projectId, myRole, canUpload, onUseInChat, }) {
    const [items, setItems] = useState([]);
    const [members, setMembers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const [kind, setKind] = useState("");
    const [query, setQuery] = useState("");
    const [preview, setPreview] = useState(null);
    const [pendingDelete, setPendingDelete] = useState(null);
    const session = getCachedSession();
    const currentUsername = session?.username ?? "";
    const currentUserId = members.find((m) => m.username === currentUsername)?.userId;
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [res, memberRes] = await Promise.all([
                listProjectMedia(projectId, {
                    kind: kind || undefined,
                    q: query.trim() || undefined,
                    limit: 200,
                }),
                listMembers(projectId).catch(() => ({ members: [] })),
            ]);
            setItems(res.items);
            setMembers(Array.isArray(memberRes) ? memberRes : memberRes.members ?? []);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, [projectId, kind, query]);
    useEffect(() => {
        void load();
    }, [load]);
    function uploaderLabel(userId) {
        if (userId == null)
            return "Unknown";
        const m = members.find((row) => row.userId === userId);
        return m?.displayName || m?.username || `User #${userId}`;
    }
    function canDeleteItem(item) {
        if (isProjectOwnerRole(myRole))
            return true;
        if (myRole === "contributor" && currentUserId != null && item.uploadedByUserId === currentUserId) {
            return true;
        }
        return false;
    }
    async function uploadFile(file) {
        setBusy(true);
        setError("");
        try {
            await uploadProjectMedia(projectId, file);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function confirmDelete() {
        if (!pendingDelete)
            return;
        const target = pendingDelete;
        setPendingDelete(null);
        try {
            await deleteProjectMedia(projectId, target.id);
            setItems((prev) => prev.filter((row) => row.id !== target.id));
            if (preview?.id === target.id)
                setPreview(null);
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    return (_jsxs("div", { className: "project-tab-body", children: [_jsxs("div", { className: "project-media-toolbar", children: [_jsx("div", { className: "project-media-filters", role: "group", "aria-label": "Media type", children: MEDIA_KIND_FILTERS.map((f) => (_jsx("button", { type: "button", className: `btn btn-sm${kind === f.id ? " btn-primary" : " btn-ghost"}`, onClick: () => setKind(f.id), children: f.label }, f.id || "all"))) }), _jsx("input", { type: "search", className: "input", placeholder: "Search filename or prompt", value: query, onChange: (e) => setQuery(e.target.value) })] }), canUpload ? (_jsxs("label", { className: `media-upload-zone${dragOver ? " media-upload-zone--active" : ""}`, onDragOver: (e) => {
                    e.preventDefault();
                    setDragOver(true);
                }, onDragLeave: () => setDragOver(false), onDrop: (e) => {
                    e.preventDefault();
                    setDragOver(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file)
                        void uploadFile(file);
                }, children: [_jsx("input", { type: "file", hidden: true, disabled: busy, onChange: (e) => {
                            const file = e.target.files?.[0];
                            e.target.value = "";
                            if (file)
                                void uploadFile(file);
                        } }), busy ? "Uploading…" : "Drop a file here or click to upload"] })) : null, error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, !loading && items.length === 0 ? (_jsx("p", { className: "empty-state", children: "No media yet." })) : (_jsx("div", { className: "project-media-grid", children: items.map((item) => (_jsxs("article", { className: "project-media-card", children: [_jsx("button", { type: "button", className: "project-media-thumb", onClick: () => setPreview(item), "aria-label": `Preview ${item.fileName}`, children: item.kind === "image" ? (_jsx("img", { src: item.url, alt: item.fileName })) : item.kind === "video" ? (_jsx("video", { src: item.url, muted: true })) : (_jsx("span", { className: "project-media-kind", children: item.kind })) }), _jsxs("div", { className: "project-media-card-body", children: [_jsx("strong", { className: "project-media-name", title: item.fileName, children: item.fileName }), _jsxs("span", { className: "project-media-meta", children: [formatMediaBytes(item.sizeBytes), " \u00B7 ", formatMediaDate(item.createdAt)] }), _jsxs("span", { className: "project-media-meta", children: ["Uploaded by ", uploaderLabel(item.uploadedByUserId)] }), _jsxs("div", { className: "project-media-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => {
                                                queueMediaForChat(item, projectId);
                                                onUseInChat();
                                            }, children: "Use in chat" }), _jsx("a", { className: "btn btn-ghost btn-sm", href: item.url, target: "_blank", rel: "noreferrer", children: "Download" }), canDeleteItem(item) ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => setPendingDelete(item), children: "Delete" })) : null] })] })] }, item.id))) })), _jsx(Modal, { open: preview != null, title: preview?.fileName ?? "Preview", onClose: () => setPreview(null), panelClassName: "project-media-preview-panel", children: preview?.kind === "image" ? (_jsx("img", { className: "project-media-preview", src: preview.url, alt: preview.fileName })) : preview?.kind === "video" ? (_jsx("video", { className: "project-media-preview", src: preview.url, controls: true })) : preview ? (_jsx("p", { children: _jsxs("a", { href: preview.url, target: "_blank", rel: "noreferrer", children: ["Download ", preview.fileName] }) })) : null }), _jsx(ConfirmModal, { open: pendingDelete != null, title: "Delete media", message: pendingDelete ? `Delete “${pendingDelete.fileName}”? This cannot be undone.` : "", emphasize: pendingDelete?.fileName, emphasizeDanger: true, danger: true, confirmLabel: "Delete", cancelLabel: "Cancel", onConfirm: () => void confirmDelete(), onCancel: () => setPendingDelete(null) })] }));
}
function SettingsTab({ projectId, canEdit }) {
    const { confirm } = useConfirm();
    const [config, setConfig] = useState(null);
    const [memories, setMemories] = useState([]);
    const [memoryTotal, setMemoryTotal] = useState(0);
    const [memoryFilter, setMemoryFilter] = useState("");
    const [grants, setGrants] = useState([]);
    const [versions, setVersions] = useState([]);
    const [ownedProjects, setOwnedProjects] = useState([]);
    const [grantSourceId, setGrantSourceId] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [customPrompt, setCustomPrompt] = useState("");
    const [memoryEnabled, setMemoryEnabled] = useState(true);
    const [memoryAutoCapture, setMemoryAutoCapture] = useState(true);
    const [useProjectResources, setUseProjectResources] = useState(true);
    const [useGrantedMemory, setUseGrantedMemory] = useState(true);
    const [newMemory, setNewMemory] = useState("");
    const [busy, setBusy] = useState(false);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [cfg, memRes, grantRes] = await Promise.all([
                getProjectConfig(projectId),
                listProjectMemories(projectId, {
                    origin: memoryFilter || undefined,
                    limit: MEMORY_PAGE_SIZE,
                }),
                listMemoryGrants(projectId),
            ]);
            setConfig(cfg);
            setCustomPrompt(cfg.customPrompt ?? "");
            setMemoryEnabled(cfg.memoryEnabled);
            setMemoryAutoCapture(cfg.memoryAutoCapture);
            const toggles = groundingTogglesFromPolicy(cfg.groundingPolicy);
            setUseProjectResources(toggles.useProjectResources);
            setUseGrantedMemory(toggles.useGrantedMemory);
            setMemories(memRes.memories);
            setMemoryTotal(memRes.total);
            setGrants(grantRes.grants);
            if (canEdit) {
                const [verRes, mine] = await Promise.all([
                    listProjectConfigVersions(projectId),
                    listProjects("mine", { limit: 100 }),
                ]);
                setVersions(verRes.versions);
                setOwnedProjects(mine.projects.filter((p) => isProjectOwnerRole(p.myRole) && p.id !== projectId));
            }
            else {
                setVersions([]);
                setOwnedProjects([]);
            }
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, [projectId, canEdit, memoryFilter]);
    useEffect(() => {
        void load();
    }, [load]);
    const grantable = ownedProjects.filter((p) => !grants.some((g) => g.sourceProjectId === p.id && !g.revokedAt));
    async function saveConfig() {
        setBusy(true);
        setError("");
        try {
            await updateProjectConfig(projectId, {
                customPrompt: customPrompt.trim() || null,
                memoryEnabled,
                memoryAutoCapture,
                groundingPolicy: groundingPolicyFromToggles({ useProjectResources, useGrantedMemory }),
            });
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function addMemory() {
        if (!newMemory.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await createProjectMemory(projectId, newMemory.trim());
            setNewMemory("");
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function toggleMemory(mem) {
        try {
            await updateProjectMemory(projectId, mem.id, { enabled: !mem.enabled });
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function deleteMemory(id) {
        try {
            await deleteProjectMemory(projectId, id);
            setMemories((prev) => prev.filter((m) => m.id !== id));
            setMemoryTotal((prev) => Math.max(0, prev - 1));
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function deleteAllLearned() {
        const ok = await confirm({
            title: "Delete all learned facts",
            message: "Every fact learned automatically from this project's chats will be deleted for all members, and will not be learned again from those chats. Facts you added by hand are kept.",
            confirmLabel: "Delete learned facts",
            danger: true,
        });
        if (ok !== true)
            return;
        setBusy(true);
        setError("");
        try {
            await deleteAllAutoProjectMemories(projectId);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function addGrant() {
        if (!grantSourceId)
            return;
        setBusy(true);
        setError("");
        try {
            await createMemoryGrant(projectId, grantSourceId);
            setGrantSourceId("");
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function revokeGrant(sourceProjectId) {
        try {
            await revokeMemoryGrant(projectId, sourceProjectId);
            setGrants((prev) => prev.filter((g) => g.sourceProjectId !== sourceProjectId));
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function restoreVersion(version) {
        setBusy(true);
        setError("");
        try {
            await updateProjectConfig(projectId, {
                customPrompt: version.customPrompt ?? null,
                memoryEnabled: version.memoryEnabled,
                memoryAutoCapture: version.memoryAutoCapture,
                groundingPolicy: version.groundingPolicy ?? {},
            });
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("div", { className: "project-tab-body", children: [error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, _jsxs("section", { className: "settings-section", children: [_jsx("h3", { children: "Custom prompt" }), _jsx("textarea", { value: customPrompt, onChange: (e) => setCustomPrompt(e.target.value), maxLength: 12000, rows: 6, disabled: !canEdit, placeholder: "Define how the project's assistant should behave\u2026" })] }), _jsxs("section", { className: "settings-section", children: [_jsx("h3", { children: "Memory" }), _jsxs("label", { className: "form-field form-field--inline", children: [_jsx("input", { type: "checkbox", checked: memoryEnabled, onChange: (e) => setMemoryEnabled(e.target.checked), disabled: !canEdit }), _jsx("span", { children: "Enable project memory (scoped to this project's chats and resources)" })] }), _jsxs("label", { className: "form-field form-field--inline", children: [_jsx("input", { type: "checkbox", checked: memoryAutoCapture, onChange: (e) => setMemoryAutoCapture(e.target.checked), disabled: !canEdit || !memoryEnabled }), _jsx("span", { children: "Automatically learn from project chats" })] }), _jsx("p", { className: "form-hint", children: "Learned facts are shared with every member of this project. Personal memory is never used in project chats, and personal or sensitive details are never captured here." }), _jsxs("div", { className: "memory-toolbar", children: [_jsxs("h4", { children: ["Memory items", memoryTotal ? ` (${memoryTotal})` : ""] }), _jsx("div", { className: "memory-filters", children: MEMORY_ORIGIN_FILTERS.map((filter) => (_jsx("button", { type: "button", className: `settings-row__action${memoryFilter === filter.id ? " is-active" : ""}`, onClick: () => setMemoryFilter(filter.id), children: filter.label }, filter.id))) })] }), canEdit ? (_jsxs("div", { className: "memory-add", children: [_jsx("input", { type: "text", value: newMemory, onChange: (e) => setNewMemory(e.target.value), maxLength: 500, placeholder: "Add a memory item\u2026" }), _jsx("button", { type: "button", className: "btn btn-primary", disabled: busy || !newMemory.trim(), onClick: () => void addMemory(), children: "Add" })] })) : null, _jsx("div", { className: "settings-list", children: memories.length === 0 ? (_jsx("div", { className: "settings-row", children: _jsx("span", { className: "settings-row__hint", children: "No memory items." }) })) : (memories.map((m) => {
                            const learned = m.origin === "auto_chat";
                            return (_jsx("div", { className: `settings-row-block${m.enabled ? "" : " is-dimmed"} settings-row-block--stacked`, children: _jsxs("div", { className: "settings-row", children: [_jsxs("div", { className: "settings-row__meta", children: [_jsx("span", { className: "settings-row__title", children: m.content }), _jsxs("span", { className: "settings-row__hint", children: [_jsx("span", { className: "settings-memory-chip", children: learned ? "learned" : "manual" }), learned && m.category ? _jsx("span", { className: "settings-memory-chip", children: m.category }) : null, learned && m.sourceSessionId ? (_jsx(Link, { to: `/projects/${encodeURIComponent(projectId)}?session=${encodeURIComponent(m.sourceSessionId)}`, children: m.sourceSessionTitle || "Source chat" })) : null] })] }), canEdit ? (_jsxs("div", { className: "settings-row__trail", children: [_jsx("button", { type: "button", className: "settings-row__action", onClick: () => void toggleMemory(m), children: m.enabled ? "Disable" : "Enable" }), _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", onClick: () => void deleteMemory(m.id), children: "Delete" })] })) : null] }) }, m.id));
                        })) }), memoryTotal > memories.length ? (_jsxs("p", { className: "form-hint", children: ["Showing the ", memories.length, " most recently updated of ", memoryTotal, " facts."] })) : null, canEdit ? (_jsx("div", { className: "memory-danger-actions", children: _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: busy, onClick: () => void deleteAllLearned(), children: "Delete all learned facts" }) })) : null] }), _jsxs("section", { className: "settings-section", children: [_jsx("h3", { children: "Grounding" }), _jsx("p", { className: "form-hint", children: "Control what the model may read on each project chat turn." }), _jsxs("label", { className: "form-field form-field--inline", children: [_jsx("input", { type: "checkbox", checked: useProjectResources, onChange: (e) => setUseProjectResources(e.target.checked), disabled: !canEdit }), _jsx("span", { children: "Use project resources (Knowledge files) in chat" })] }), _jsxs("label", { className: "form-field form-field--inline", children: [_jsx("input", { type: "checkbox", checked: useGrantedMemory, onChange: (e) => setUseGrantedMemory(e.target.checked), disabled: !canEdit }), _jsx("span", { children: "Use granted memory from other projects" })] })] }), _jsxs("section", { className: "settings-section", children: [_jsx("h3", { children: "Cross-project memory grants" }), _jsx("p", { className: "form-hint", children: "Memory grants let this project read memory items from another project where you are also an Owner." }), canEdit ? (_jsxs("div", { className: "memory-add", children: [_jsxs("select", { className: "input", value: grantSourceId, onChange: (e) => setGrantSourceId(e.target.value), children: [_jsx("option", { value: "", children: "Select a source project\u2026" }), grantable.map((p) => (_jsx("option", { value: p.id, children: p.name }, p.id)))] }), _jsx("button", { type: "button", className: "btn btn-primary", disabled: busy || !grantSourceId, onClick: () => void addGrant(), children: "Grant" })] })) : null, canEdit && grantable.length === 0 ? (_jsx("p", { className: "form-hint", children: "You need to be Owner of another project to create a grant." })) : null, _jsxs("ul", { className: "grant-list", children: [grants.map((g) => (_jsxs("li", { className: "grant-item", children: [_jsx("span", { children: g.sourceProjectName ?? g.sourceProjectId }), canEdit ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void revokeGrant(g.sourceProjectId), children: "Revoke" })) : null] }, g.id))), grants.length === 0 ? _jsx("li", { className: "empty-state", children: "No active grants." }) : null] })] }), canEdit ? (_jsxs("section", { className: "settings-section", children: [_jsx("h3", { children: "Configuration history" }), _jsx("p", { className: "form-hint", children: "Restore creates a new revision from a previous snapshot. Old versions are never mutated." }), _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Revision" }), _jsx("th", { children: "Created" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [versions.map((v) => {
                                        const active = config?.configVersionId === v.id;
                                        return (_jsxs("tr", { children: [_jsxs("td", { children: [v.revision, active ? " (active)" : ""] }), _jsx("td", { children: v.createdAt ? new Date(v.createdAt).toLocaleString() : "—" }), _jsx("td", { children: !active ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", disabled: busy, onClick: () => void restoreVersion(v), children: "Restore" })) : null })] }, v.id));
                                    }), versions.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 3, className: "empty-state", children: "No saved versions yet." }) }) : null] })] })] })) : null, canEdit ? (_jsx("div", { className: "settings-actions", children: _jsx("button", { type: "button", className: "btn btn-primary", disabled: busy, onClick: () => void saveConfig(), children: busy ? "Saving…" : "Save settings" }) })) : null] }));
}
function MembersTab({ projectId, canManageMembers, myRole, }) {
    const [members, setMembers] = useState([]);
    const [invitations, setInvitations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [addOpen, setAddOpen] = useState(false);
    const [invOpen, setInvOpen] = useState(false);
    const [search, setSearch] = useState("");
    const [results, setResults] = useState([]);
    const [selectedUser, setSelectedUser] = useState(null);
    const [newRole, setNewRole] = useState("viewer");
    const [busy, setBusy] = useState(false);
    const [invRole, setInvRole] = useState("viewer");
    const [lastToken, setLastToken] = useState(null);
    const [notifyUserId, setNotifyUserId] = useState("");
    const [invitees, setInvitees] = useState([]);
    const [emailWarning, setEmailWarning] = useState("");
    const roleOptions = assignableProjectRoles(myRole);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [memRes, invRes] = await Promise.all([
                listMembers(projectId),
                listInvitations(projectId),
            ]);
            setMembers(memRes.members);
            setInvitations(invRes.invitations);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, [projectId]);
    useEffect(() => {
        void load();
    }, [load]);
    useEffect(() => {
        if (!invOpen || !canManageMembers) {
            setInvitees([]);
            return;
        }
        let active = true;
        listInvitableUsers(projectId, undefined, 50)
            .then((res) => {
            if (active)
                setInvitees(res.users);
        })
            .catch(() => {
            if (active)
                setInvitees([]);
        });
        return () => {
            active = false;
        };
    }, [invOpen, canManageMembers, projectId]);
    useEffect(() => {
        if (!addOpen || !search.trim()) {
            setResults([]);
            return;
        }
        let active = true;
        listInvitableUsers(projectId, search.trim())
            .then((res) => {
            if (active)
                setResults(res.users);
        })
            .catch(() => {
            if (active)
                setResults([]);
        });
        return () => {
            active = false;
        };
    }, [addOpen, search, projectId]);
    async function addUser() {
        if (!selectedUser)
            return;
        setBusy(true);
        setError("");
        try {
            await addMember(projectId, selectedUser.id, newRole);
            setAddOpen(false);
            setSelectedUser(null);
            setSearch("");
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function changeRole(userId, role) {
        try {
            await updateMemberRole(projectId, userId, role);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function removeUser(userId) {
        try {
            await removeMember(projectId, userId);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function createInv() {
        setBusy(true);
        setError("");
        setEmailWarning("");
        try {
            const inv = await createInvitation({
                projectId,
                role: invRole,
                notifyUserId: notifyUserId ? Number(notifyUserId) : undefined,
            });
            setLastToken(inv.token ?? null);
            if (inv.emailWarning)
                setEmailWarning(inv.emailWarning);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function revokeInv(id) {
        try {
            await revokeInvitation(projectId, id);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    return (_jsxs("div", { className: "project-tab-body", children: [error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, canManageMembers ? (_jsxs("div", { className: "members-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary", onClick: () => setAddOpen(true), children: "Add member" }), _jsx("button", { type: "button", className: "btn", onClick: () => { setInvOpen(true); setLastToken(null); }, children: "Create invitation link" })] })) : null, _jsx("h3", { children: "Members" }), _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "User" }), _jsx("th", { children: "Role" }), _jsx("th", {})] }) }), _jsx("tbody", { children: members.map((m) => {
                            const canEditRow = canManageMembers &&
                                m.role !== "primary_owner" &&
                                (m.role !== "owner" || isPrimaryOwnerRole(myRole));
                            return (_jsxs("tr", { children: [_jsx("td", { children: m.displayName ?? m.username ?? `User #${m.userId}` }), _jsx("td", { children: canEditRow ? (_jsx("select", { value: m.role, onChange: (e) => void changeRole(m.userId, e.target.value), children: roleOptions.map((r) => _jsx("option", { value: r, children: projectRoleLabel(r) }, r)) })) : (_jsx("span", { children: projectRoleLabel(m.role) })) }), _jsx("td", { children: canEditRow ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void removeUser(m.userId), children: "Remove" })) : null })] }, `${m.projectId}:${m.userId}`));
                        }) })] }), _jsx("h3", { children: "Invitation links" }), _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Role" }), _jsx("th", { children: "Uses" }), _jsx("th", { children: "Expires" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [invitations.map((inv) => (_jsxs("tr", { children: [_jsx("td", { children: projectRoleLabel(inv.role) }), _jsxs("td", { children: [inv.useCount, " / ", inv.maxUses] }), _jsx("td", { children: inv.expiresAt ?? "—" }), _jsx("td", { children: inv.isRevoked ? "revoked" : inv.isExpired ? "expired" : inv.isExhausted ? "exhausted" : "active" }), _jsx("td", { children: canManageMembers && !inv.isRevoked ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void revokeInv(inv.id), children: "Revoke" })) : null })] }, inv.id))), invitations.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 5, className: "empty-state", children: "No invitation links." }) }) : null] })] }), _jsxs(Modal, { open: addOpen, title: "Add member", onClose: () => {
                    setAddOpen(false);
                    setSearch("");
                    setSelectedUser(null);
                }, panelClassName: "modal-panel--project-form", children: [_jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Search users" }), _jsx("input", { type: "search", value: search, onChange: (e) => setSearch(e.target.value), autoFocus: true, placeholder: "Type a username\u2026" })] }), search.trim() ? (_jsxs("div", { className: "user-search-results", children: [results.map((u) => (_jsxs("button", { type: "button", className: `user-search-row${selectedUser?.id === u.id ? " user-search-row--selected" : ""}`, onClick: () => setSelectedUser(u), children: [_jsx("span", { children: u.displayName ?? u.username }), u.displayName && u.username && u.displayName !== u.username ? (_jsx("small", { children: u.username })) : null] }, u.id))), results.length === 0 ? _jsx("p", { className: "user-search-empty", children: "No users found." }) : null] })) : null, selectedUser ? (_jsxs("div", { className: "user-search-selected", children: [_jsx("span", { children: selectedUser.displayName ?? selectedUser.username }), _jsx("small", { children: "Selected" })] })) : search.trim() ? null : (_jsx("p", { className: "form-hint", children: "Type a username, then choose a role." })), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Role" }), _jsx("select", { value: newRole, onChange: (e) => setNewRole(e.target.value), children: roleOptions.map((r) => _jsx("option", { value: r, children: projectRoleLabel(r) }, r)) })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary", disabled: !selectedUser || busy, onClick: () => void addUser(), children: busy ? "Adding…" : "Add" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => {
                                    setAddOpen(false);
                                    setSearch("");
                                    setSelectedUser(null);
                                }, children: "Cancel" })] })] }), _jsxs(Modal, { open: invOpen, title: "Create invitation link", onClose: () => { setInvOpen(false); setLastToken(null); setEmailWarning(""); setNotifyUserId(""); }, panelClassName: "modal-panel--project-form", children: [_jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Role" }), _jsxs("select", { value: invRole, onChange: (e) => setInvRole(e.target.value), children: [_jsx("option", { value: "contributor", children: "Contributor" }), _jsx("option", { value: "viewer", children: "Viewer" })] })] }), _jsx("p", { className: "form-hint", children: "Invitation links never grant Owner or Primary Owner." }), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Email invite to (optional)" }), _jsxs("select", { value: notifyUserId, onChange: (e) => setNotifyUserId(e.target.value), children: [_jsx("option", { value: "", children: "Don't email \u2014 copy the link" }), invitees.map((u) => (_jsx("option", { value: String(u.id), children: u.displayName ?? u.username }, u.id)))] })] }), _jsx("p", { className: "form-hint", children: "If SMTP is not configured, the link is still created." }), emailWarning ? _jsx("div", { className: "flash", children: emailWarning }) : null, lastToken ? (_jsxs("div", { className: "invitation-token-box", children: [_jsx("p", { children: "Share this link (shown once):" }), _jsxs("code", { children: [window.location.origin, "/app/projects/invite?token=", lastToken] })] })) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary", disabled: busy, onClick: () => void createInv(), children: busy ? "Creating…" : "Create link" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => { setInvOpen(false); setLastToken(null); setEmailWarning(""); setNotifyUserId(""); }, children: "Close" })] })] })] }));
}
