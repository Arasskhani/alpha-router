import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { formatApiError, getCachedSession } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import Modal from "../components/Modal";
import RowActionsMenu, { type RowAction } from "../components/RowActionsMenu";
import ChatPanel from "../components/ChatPanel";
import ProjectRooms from "./ProjectRooms";
import ActivityView from "../components/activity/ActivityView";
import { formatRequests, formatSpend, formatTokens } from "../components/activity/formatters";
import { USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
import {
  addMember,
  archiveProject,
  createInvitation,
  createMemoryGrant,
  createProjectMemory,
  deleteAllAutoProjectMemories,
  deleteProject,
  deleteProjectMedia,
  deleteProjectMemory,
  deleteProjectResource,
  getProject,
  getProjectConfig,
  getProjectOverview,
  groundingPolicyFromToggles,
  groundingTogglesFromPolicy,
  leaveProject,
  listInvitableUsers,
  listInvitations,
  listMembers,
  listMemoryGrants,
  listProjectConfigVersions,
  listProjectMedia,
  listProjectMemories,
  listProjectResources,
  listProjects,
  MAX_PROJECT_RESOURCE_UPLOAD_FILES,
  needsPublicTypedConfirm,
  PROJECT_MEDIA_ATTACH_CONSUMED_EVENT,
  PROJECT_MEDIA_ATTACH_EVENT,
  assignableProjectRoles,
  isPrimaryOwnerRole,
  isProjectOwnerRole,
  projectRoleLabel,
  projectResourceUserStatus,
  projectResourceUserStatusTone,
  projectResourceTooManyFilesMessage,
  purgeProject,
  queueProjectMediaForChat,
  readQueuedProjectMediaAttach,
  removeMember,
  restoreProject,
  revokeInvitation,
  revokeMemoryGrant,
  updateMemberRole,
  updateProject,
  updateProjectConfig,
  updateProjectMemory,
  uploadProjectMedia,
  uploadProjectResource,
  type InvitationRecord,
  type InvitableUser,
  type MemoryGrant,
  type ProjectConfig,
  type ProjectConfigVersion,
  type ProjectMediaAttachPayload,
  type ProjectMediaItem,
  type ProjectMediaKind,
  type ProjectMemberRecord,
  type ProjectMemory,
  type ProjectOverview,
  type ProjectRecord,
  type ProjectResource,
  type ProjectRole,
  type ProjectVisibility,
} from "../lib/projectsApi";
import { useConfirm } from "../context/ConfirmContext";
import { agentStatusTone } from "../lib/agentPlatform";
import { formatLocalDate, formatLocalDateTime } from "../lib/dateTime";

type Tab = "rooms" | "overview" | "chats" | "resources" | "media" | "settings" | "members" | "activity";

const MEDIA_KIND_FILTERS: Array<{ id: "" | ProjectMediaKind; label: string }> = [
  { id: "", label: "All" },
  { id: "image", label: "Images" },
  { id: "video", label: "Videos" },
  { id: "document", label: "Documents" },
  { id: "other", label: "Other" },
];

const MEMORY_PAGE_SIZE = 100;

const MEMORY_ORIGIN_FILTERS: Array<{ id: "" | "manual" | "auto"; label: string }> = [
  { id: "", label: "All" },
  { id: "manual", label: "Manual" },
  { id: "auto", label: "Learned" },
];

export default function ProjectWorkspacePage() {
  const { projectId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("chats");
  const [pendingMedia, setPendingMedia] = useState<ProjectMediaAttachPayload | null>(null);

  const projectsListTo = location.pathname.startsWith("/admin")
    ? "/admin/projects"
    : "/app/projects";

  const loadProject = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const p = await getProject(projectId);
      setProject(p);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  useEffect(() => {
    if (searchParams.get("session")) setTab("chats");
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
  const projectReadOnly = Boolean(
    project && (project.myRole === "viewer" || !project.isMember),
  );
  const roleLabel = projectRoleLabel(project?.myRole);

  useEffect(() => {
    if (tab === "activity" && !canEdit) setTab("chats");
    if (tab === "rooms" && project && !project.isMember) setTab("chats");
  }, [tab, canEdit, project]);

  const conversationTabs: Tab[] = project?.isMember ? ["chats", "rooms"] : ["chats"];
  const tabs: Tab[] = canEdit
    ? [...conversationTabs, "resources", "media", "overview", "activity", "members", "settings"]
    : [...conversationTabs, "resources", "media", "overview", "members", "settings"];

  const tabContent =
    !project || tab === "chats"
      ? null
      : tab === "rooms"
        ? (
          <ProjectRooms
            projectId={project.id}
            canWrite={canUpload}
            onHandoff={(targetSessionId) => {
              navigate(`?session=${encodeURIComponent(targetSessionId)}`);
              setTab("chats");
            }}
          />
        )
      : tab === "overview"
        ? (
          <OverviewTab
            project={project}
            onSelectTab={setTab}
            canOpenActivity={canEdit}
          />
        )
        : tab === "activity" && canEdit
          ? (
            <ActivityView
              scope="project"
              projectId={project.id}
              title={USAGE_AND_ACTIVITY_LABEL}
            />
          )
          : tab === "resources"
            ? <ResourcesTab projectId={project.id} canUpload={canUpload} />
            : tab === "media"
              ? (
                <MediaTab
                  projectId={project.id}
                  myRole={project.myRole ?? null}
                  canUpload={canUpload}
                  onUseInChat={() => setTab("chats")}
                />
              )
              : tab === "settings"
                ? <SettingsTab projectId={project.id} canEdit={canEdit} />
                : (
                  <MembersTab
                    projectId={project.id}
                    canManageMembers={canManageMembers}
                    myRole={project.myRole ?? null}
                  />
                );

  return (
    <ChatPanel
      projectId={projectId}
      projectReadOnly={projectReadOnly}
      enableModelChrome={tab === "chats"}
      hideChatSidebar={tab === "rooms"}
      onProjectChatFocus={() => setTab("chats")}
      projectSidebarHeader={
        <div className="alpha-router-project-identity">
          <Link to={projectsListTo} className="alpha-router-project-identity__back">
            ← Projects
          </Link>
          <div className="alpha-router-project-identity__name">
            {project?.name ?? "Project"}
          </div>
          <div className="alpha-router-project-identity__meta">
            <span>Shared project chat</span>
            {roleLabel ? <span className="project-role-chip">{roleLabel}</span> : null}
          </div>
        </div>
      }
      projectToolbar={
        <div className="project-chat-toolbar">
          <div className="project-chat-toolbar__row">
            <div className="project-chat-toolbar__title">
              {tab === "rooms" ? (
                <Link to={projectsListTo} className="project-chat-toolbar__back">
                  ← Projects
                </Link>
              ) : null}
              <h1>{project?.name ?? "Project"}</h1>
              {roleLabel ? <span className="project-role-chip project-role-chip--light">{roleLabel}</span> : null}
            </div>
            {project ? (
              <ProjectActionsMenu
                project={project}
                canEdit={canEdit}
                canLifecycle={canLifecycle}
                onChanged={loadProject}
                onDeleted={() => navigate(projectsListTo)}
              />
            ) : null}
          </div>
          <nav className="project-tabs" aria-label="Project sections">
            {tabs.map((t) => (
              <button
                key={t}
                type="button"
                className={`project-tab${tab === t ? " project-tab--active" : ""}`}
                onClick={() => setTab(t)}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </nav>
          {error ? <div className="flash flash-error">{error}</div> : null}
          {project?.status === "archived" ? (
            <div className="flash">This project is archived. Restore it from the menu to show it in Explore again.</div>
          ) : null}
          {project?.status === "deletion_pending" ? (
            <div className="flash flash-error">This project is pending deletion. The Primary Owner can purge it now, or the nightly job will remove it after the retention period.</div>
          ) : null}
          {loading && !project ? <div className="loading-state">Loading…</div> : null}
        </div>
      }
      projectBanner={
        tab === "chats" ? (
          <>
            {pendingMedia ? (
              <div className="flash">
                Queued for the next chat message: <strong>{pendingMedia.fileName}</strong>
              </div>
            ) : null}
            {projectReadOnly && project ? (
              <p className="form-hint project-chat-readonly-hint">
                You can read project chats. Only Owners and Contributors can send messages.
              </p>
            ) : null}
          </>
        ) : null
      }
      mainOverride={tabContent}
    />
  );
}

function ProjectActionsMenu({
  project,
  canEdit,
  canLifecycle,
  onChanged,
  onDeleted,
}: {
  project: ProjectRecord;
  canEdit: boolean;
  canLifecycle: boolean;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [confirmPublic, setConfirmPublic] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [visibility, setVisibility] = useState<ProjectVisibility>(project.visibility);
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
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    setBusy(true);
    try {
      await deleteProject(project.id);
      onDeleted();
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
    }
  }

  async function doLeave() {
    setBusy(true);
    try {
      await leaveProject(project.id);
      onDeleted();
    } catch (e) {
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
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function doRestore() {
    setBusy(true);
    setErr("");
    try {
      await restoreProject(project.id);
      onChanged();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function doPurge() {
    setBusy(true);
    try {
      await purgeProject(project.id);
      onDeleted();
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
    }
  }

  const actions: RowAction[] = [];
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
    } else {
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

  if (actions.length === 0) return null;

  return (
    <>
      <RowActionsMenu actions={actions} />
      <Modal open={editOpen} title="Edit project" onClose={() => setEditOpen(false)} panelClassName="modal-panel--project-form">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void saveEdit();
          }}
        >
          <label className="form-field">
            <span>Name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
          </label>
          <label className="form-field">
            <span>Description</span>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} rows={3} />
          </label>
          <label className="form-field">
            <span>Visibility</span>
            <select value={visibility} onChange={(e) => setVisibility(e.target.value as ProjectVisibility)}>
              <option value="private">Private (members only)</option>
              <option value="public">Public (all authenticated users)</option>
            </select>
          </label>
          {visibility === "public" && project.visibility !== "public" ? (
            <p className="form-hint form-hint--warning">
              Making this project public grants read access to every authenticated user. Only do this if all resources and chat content are safe to share organization-wide.
            </p>
          ) : null}
          {err ? <p className="form-error">{err}</p> : null}
          <div className="dialog-actions">
            <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setEditOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmModal
        open={confirmPublic}
        title="Make this project public"
        message="Type PUBLIC to confirm. Every authenticated user will be able to read this project's chats, resources, and media."
        danger
        confirmLabel="Make public"
        cancelLabel="Cancel"
        promptLabel="Type PUBLIC to confirm"
        promptExactMatch="PUBLIC"
        onConfirm={() => void commitEdit()}
        onCancel={() => setConfirmPublic(false)}
      />

      <ConfirmModal
        open={confirmDelete}
        title="Delete project"
        message={`This marks “${project.name}” for deletion. Members keep access until an Owner purges it or the retention job removes it.`}
        danger
        confirmLabel="Mark for deletion"
        cancelLabel="Cancel"
        promptLabel="Type the project name to confirm"
        promptExactMatch={project.name}
        onConfirm={() => void doDelete()}
        onCancel={() => setConfirmDelete(false)}
      />

      <ConfirmModal
        open={confirmArchive}
        title="Archive project"
        message={`“${project.name}” will leave Explore. Members can still open it from My projects until you restore it.`}
        confirmLabel="Archive"
        cancelLabel="Cancel"
        onConfirm={() => void doArchive()}
        onCancel={() => setConfirmArchive(false)}
      />

      <ConfirmModal
        open={confirmPurge}
        title="Purge project"
        message={`Permanently delete “${project.name}”, including chats, resources, and project media. This cannot be undone.`}
        danger
        confirmLabel="Purge permanently"
        cancelLabel="Cancel"
        promptLabel="Type the project name to confirm"
        promptExactMatch={project.name}
        onConfirm={() => void doPurge()}
        onCancel={() => setConfirmPurge(false)}
      />

      <ConfirmModal
        open={confirmLeave}
        title="Leave project"
        message="You will no longer have access to this project. An Owner can re-invite you later."
        confirmLabel="Leave"
        cancelLabel="Cancel"
        onConfirm={() => void doLeave()}
        onCancel={() => setConfirmLeave(false)}
      />
    </>
  );
}

function projectVisibilityLabel(visibility: ProjectVisibility): string {
  return visibility === "public" ? "Public" : "Private";
}

function projectOverviewStatusLabel(status: ProjectRecord["status"]): string {
  if (status === "archived") return "Archived";
  if (status === "deletion_pending") return "Pending deletion";
  return "Active";
}

function OverviewStatCard({
  title,
  value,
  onOpen,
}: {
  title: string;
  value: string;
  onOpen?: () => void;
}) {
  const inner = (
    <>
      <p className="overview-kpi-card__title">{title}</p>
      <p className="overview-kpi-card__value">{value}</p>
    </>
  );
  if (onOpen) {
    return (
      <button
        type="button"
        className="overview-kpi-card card project-overview-kpi-btn"
        onClick={onOpen}
      >
        {inner}
      </button>
    );
  }
  return <article className="overview-kpi-card card">{inner}</article>;
}

function OverviewTab({
  project,
  onSelectTab,
  canOpenActivity,
}: {
  project: ProjectRecord;
  onSelectTab: (tab: Tab) => void;
  canOpenActivity: boolean;
}) {
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void getProjectOverview(project.id)
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
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
  const countValue = (n: number | undefined) =>
    counts ? String(n ?? 0) : loading ? "…" : "—";

  return (
    <div className="project-overview">
      <section className="project-overview-identity card">
        {project.description ? (
          <p className="project-overview-identity__desc">{project.description}</p>
        ) : (
          <p className="project-overview-identity__desc project-overview-identity__desc--empty">
            No description yet
          </p>
        )}
        <div className="project-overview-identity__meta">
          <span className={`project-card-badge project-card-badge--${project.visibility}`}>
            {projectVisibilityLabel(project.visibility)}
          </span>
          <span className={`project-card-badge project-card-badge--${project.status}`}>
            {projectOverviewStatusLabel(project.status)}
          </span>
          {roleLabel ? (
            <span className="project-role-chip project-role-chip--light">{roleLabel}</span>
          ) : null}
          {createdLabel !== "—" ? (
            <span className="project-overview-identity__created" title={createdTitle}>
              Created {createdLabel}
            </span>
          ) : null}
        </div>
      </section>

      <div className="overview-kpi-row">
        <OverviewStatCard
          title="Members"
          value={countValue(counts?.members)}
          onOpen={() => onSelectTab("members")}
        />
        <OverviewStatCard
          title="Chats"
          value={countValue(counts?.chats)}
          onOpen={() => onSelectTab("chats")}
        />
        <OverviewStatCard
          title="Resources"
          value={countValue(counts?.resources)}
          onOpen={() => onSelectTab("resources")}
        />
        <OverviewStatCard
          title="Media"
          value={countValue(counts?.media)}
          onOpen={() => onSelectTab("media")}
        />
      </div>

      {canOpenActivity && (usage || loading) ? (
        <section className="project-overview-usage card">
          <header className="overview-card-head">
            <h3>Last {usage?.windowDays ?? 30} days</h3>
            <button
              type="button"
              className="overview-explore-link"
              onClick={() => onSelectTab("activity")}
            >
              Open Activity →
            </button>
          </header>
          <div className="overview-kpi-row">
            <OverviewStatCard title="Spend" value={usage ? formatSpend(usage.totalCostUsd) : "…"} />
            <OverviewStatCard title="Media spend" value={usage ? formatSpend(usage.mediaCostUsd) : "…"} />
            <OverviewStatCard title="Requests" value={usage ? formatRequests(usage.requests) : "…"} />
            <OverviewStatCard title="Tokens" value={usage ? formatTokens(usage.totalTokens) : "…"} />
          </div>
        </section>
      ) : null}

      {error ? <p className="form-error">{error}</p> : null}
    </div>
  );
}


function ResourcesTab({ projectId, canUpload }: { projectId: string; canUpload: boolean }) {
  const [resources, setResources] = useState<ProjectResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listProjectResources(projectId, { limit: 100 });
      setResources(res.resources);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  function resetUploadForm() {
    setFiles([]);
    setTitle("");
    if (fileInput.current) fileInput.current.value = "";
  }

  function onUploadFilesChange(list: FileList | null) {
    const selected = Array.from(list || []);
    if (selected.length > MAX_PROJECT_RESOURCE_UPLOAD_FILES) {
      resetUploadForm();
      setError(projectResourceTooManyFilesMessage(selected.length));
      return;
    }
    setError("");
    setFiles(selected);
    if (selected.length !== 1) setTitle("");
  }

  async function upload() {
    if (files.length === 0) return;
    if (files.length > MAX_PROJECT_RESOURCE_UPLOAD_FILES) {
      setError(projectResourceTooManyFilesMessage(files.length));
      return;
    }
    setBusy(true);
    setError("");
    const failures: string[] = [];
    setUploadProgress({ current: 0, total: files.length });
    try {
      for (const [index, file] of files.entries()) {
        setUploadProgress({ current: index + 1, total: files.length });
        try {
          await uploadProjectResource(
            projectId,
            file,
            files.length === 1 ? title.trim() || undefined : undefined,
          );
        } catch (err) {
          failures.push(`${file.name}: ${formatApiError(err)}`);
        }
      }
      resetUploadForm();
      await load();
      if (failures.length) setError(failures.join(" "));
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }

  async function remove(id: string) {
    try {
      await deleteProjectResource(projectId, id);
      setResources((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div className="project-tab-body">
      {canUpload ? (
        <div className="project-upload">
          <h3>Upload resource</h3>
          <input
            ref={fileInput}
            type="file"
            multiple
            onChange={(e) => onUploadFilesChange(e.target.files)}
            disabled={busy}
          />
          {files.length <= 1 ? (
            <input
              type="text"
              placeholder="Title (optional)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input"
              disabled={busy}
            />
          ) : (
            <p className="muted-text">
              {files.length} files selected. Titles will use each file name.
            </p>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={files.length === 0 || busy}
            onClick={() => void upload()}
          >
            {uploadProgress
              ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}…`
              : files.length > 1
                ? `Upload ${files.length} files`
                : "Upload"}
          </button>
          <p className="muted-text">
            Up to {MAX_PROJECT_RESOURCE_UPLOAD_FILES} files per upload. An optional title is available only when
            uploading a single file.
          </p>
        </div>
      ) : null}
      {error ? <div className="flash flash-error">{error}</div> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}
      <table className="data-table">
        <thead>
          <tr><th>Title</th><th>Status</th><th>Uploaded</th><th></th></tr>
        </thead>
        <tbody>
          {resources.map((r) => {
            const statusLabel = projectResourceUserStatus(r);
            return (
              <tr key={r.id}>
                <td>
                  {r.title}
                  {r.failureReason ? (
                    <small className="agent-table-sub error" style={{ display: "block" }}>{r.failureReason}</small>
                  ) : null}
                </td>
                <td>
                  <span className={`agent-status ${agentStatusTone(projectResourceUserStatusTone(r))}`}>
                    {statusLabel}
                  </span>
                </td>
                <td>{r.createdAt ?? "—"}</td>
                <td>
                  {canUpload ? (
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => void remove(r.id)}>
                      Remove
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
          {resources.length === 0 && !loading ? (
            <tr><td colSpan={4} className="empty-state">No resources yet.</td></tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}


function formatMediaBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatMediaDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function queueMediaForChat(item: ProjectMediaItem, projectId: string) {
  queueProjectMediaForChat(item, projectId);
}

function MediaTab({
  projectId,
  myRole,
  canUpload,
  onUseInChat,
}: {
  projectId: string;
  myRole: ProjectRole | null;
  canUpload: boolean;
  onUseInChat: () => void;
}) {
  const [items, setItems] = useState<ProjectMediaItem[]>([]);
  const [members, setMembers] = useState<ProjectMemberRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [kind, setKind] = useState<"" | ProjectMediaKind>("");
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<ProjectMediaItem | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ProjectMediaItem | null>(null);

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
        listMembers(projectId).catch(() => ({ members: [] as ProjectMemberRecord[] })),
      ]);
      setItems(res.items);
      setMembers(Array.isArray(memberRes) ? memberRes : memberRes.members ?? []);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [projectId, kind, query]);

  useEffect(() => {
    void load();
  }, [load]);

  function uploaderLabel(userId?: number | null): string {
    if (userId == null) return "Unknown";
    const m = members.find((row) => row.userId === userId);
    return m?.displayName || m?.username || `User #${userId}`;
  }

  function canDeleteItem(item: ProjectMediaItem): boolean {
    if (isProjectOwnerRole(myRole)) return true;
    if (myRole === "contributor" && currentUserId != null && item.uploadedByUserId === currentUserId) {
      return true;
    }
    return false;
  }

  async function uploadFile(file: File) {
    setBusy(true);
    setError("");
    try {
      await uploadProjectMedia(projectId, file);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    try {
      await deleteProjectMedia(projectId, target.id);
      setItems((prev) => prev.filter((row) => row.id !== target.id));
      if (preview?.id === target.id) setPreview(null);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div className="project-tab-body">
      <div className="project-media-toolbar">
        <div className="project-media-filters" role="group" aria-label="Media type">
          {MEDIA_KIND_FILTERS.map((f) => (
            <button
              key={f.id || "all"}
              type="button"
              className={`btn btn-sm${kind === f.id ? " btn-primary" : " btn-ghost"}`}
              onClick={() => setKind(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          className="input"
          placeholder="Search filename or prompt"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {canUpload ? (
        <label
          className={`media-upload-zone${dragOver ? " media-upload-zone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files?.[0];
            if (file) void uploadFile(file);
          }}
        >
          <input
            type="file"
            hidden
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void uploadFile(file);
            }}
          />
          {busy ? "Uploading…" : "Drop a file here or click to upload"}
        </label>
      ) : null}

      {error ? <div className="flash flash-error">{error}</div> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}

      {!loading && items.length === 0 ? (
        <p className="empty-state">No media yet.</p>
      ) : (
        <div className="project-media-grid">
          {items.map((item) => (
            <article key={item.id} className="project-media-card">
              <button
                type="button"
                className="project-media-thumb"
                onClick={() => setPreview(item)}
                aria-label={`Preview ${item.fileName}`}
              >
                {item.kind === "image" ? (
                  <img src={item.url} alt={item.fileName} />
                ) : item.kind === "video" ? (
                  <video src={item.url} muted />
                ) : (
                  <span className="project-media-kind">{item.kind}</span>
                )}
              </button>
              <div className="project-media-card-body">
                <strong className="project-media-name" title={item.fileName}>{item.fileName}</strong>
                <span className="project-media-meta">
                  {formatMediaBytes(item.sizeBytes)} · {formatMediaDate(item.createdAt)}
                </span>
                <span className="project-media-meta">Uploaded by {uploaderLabel(item.uploadedByUserId)}</span>
                <div className="project-media-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      queueMediaForChat(item, projectId);
                      onUseInChat();
                    }}
                  >
                    Use in chat
                  </button>
                  <a className="btn btn-ghost btn-sm" href={item.url} target="_blank" rel="noreferrer">
                    Download
                  </a>
                  {canDeleteItem(item) ? (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setPendingDelete(item)}
                    >
                      Delete
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Modal
        open={preview != null}
        title={preview?.fileName ?? "Preview"}
        onClose={() => setPreview(null)}
        panelClassName="project-media-preview-panel"
      >
        {preview?.kind === "image" ? (
          <img className="project-media-preview" src={preview.url} alt={preview.fileName} />
        ) : preview?.kind === "video" ? (
          <video className="project-media-preview" src={preview.url} controls />
        ) : preview ? (
          <p>
            <a href={preview.url} target="_blank" rel="noreferrer">Download {preview.fileName}</a>
          </p>
        ) : null}
      </Modal>

      <ConfirmModal
        open={pendingDelete != null}
        title="Delete media"
        message={pendingDelete ? `Delete “${pendingDelete.fileName}”? This cannot be undone.` : ""}
        emphasize={pendingDelete?.fileName}
        emphasizeDanger
        danger
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}


function SettingsTab({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { confirm } = useConfirm();
  const [config, setConfig] = useState<ProjectConfig | null>(null);
  const [memories, setMemories] = useState<ProjectMemory[]>([]);
  const [memoryTotal, setMemoryTotal] = useState(0);
  const [memoryFilter, setMemoryFilter] = useState<"" | "manual" | "auto">("");
  const [grants, setGrants] = useState<MemoryGrant[]>([]);
  const [versions, setVersions] = useState<ProjectConfigVersion[]>([]);
  const [ownedProjects, setOwnedProjects] = useState<ProjectRecord[]>([]);
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
      } else {
        setVersions([]);
        setOwnedProjects([]);
      }
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [projectId, canEdit, memoryFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const grantable = ownedProjects.filter(
    (p) => !grants.some((g) => g.sourceProjectId === p.id && !g.revokedAt),
  );

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
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addMemory() {
    if (!newMemory.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createProjectMemory(projectId, newMemory.trim());
      setNewMemory("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleMemory(mem: ProjectMemory) {
    try {
      await updateProjectMemory(projectId, mem.id, { enabled: !mem.enabled });
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function deleteMemory(id: string) {
    try {
      await deleteProjectMemory(projectId, id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
      setMemoryTotal((prev) => Math.max(0, prev - 1));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function deleteAllLearned() {
    const ok = await confirm({
      title: "Delete all learned facts",
      message:
        "Every fact learned automatically from this project's chats will be deleted for all members, and will not be learned again from those chats. Facts you added by hand are kept.",
      confirmLabel: "Delete learned facts",
      danger: true,
    });
    if (ok !== true) return;
    setBusy(true);
    setError("");
    try {
      await deleteAllAutoProjectMemories(projectId);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addGrant() {
    if (!grantSourceId) return;
    setBusy(true);
    setError("");
    try {
      await createMemoryGrant(projectId, grantSourceId);
      setGrantSourceId("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function revokeGrant(sourceProjectId: string) {
    try {
      await revokeMemoryGrant(projectId, sourceProjectId);
      setGrants((prev) => prev.filter((g) => g.sourceProjectId !== sourceProjectId));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function restoreVersion(version: ProjectConfigVersion) {
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
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="project-tab-body">
      {error ? <div className="flash flash-error">{error}</div> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}

      <section className="settings-section">
        <h3>Custom prompt</h3>
        <textarea
          value={customPrompt}
          onChange={(e) => setCustomPrompt(e.target.value)}
          maxLength={12000}
          rows={6}
          disabled={!canEdit}
          placeholder="Define how the project's assistant should behave…"
        />
      </section>

      <section className="settings-section">
        <h3>Memory</h3>
        <label className="form-field form-field--inline">
          <input
            type="checkbox"
            checked={memoryEnabled}
            onChange={(e) => setMemoryEnabled(e.target.checked)}
            disabled={!canEdit}
          />
          <span>Enable project memory (scoped to this project's chats and resources)</span>
        </label>
        <label className="form-field form-field--inline">
          <input
            type="checkbox"
            checked={memoryAutoCapture}
            onChange={(e) => setMemoryAutoCapture(e.target.checked)}
            disabled={!canEdit || !memoryEnabled}
          />
          <span>Automatically learn from project chats</span>
        </label>
        <p className="form-hint">
          Learned facts are shared with every member of this project. Personal memory
          is never used in project chats, and personal or sensitive details are never
          captured here.
        </p>

        <div className="memory-toolbar">
          <h4>Memory items{memoryTotal ? ` (${memoryTotal})` : ""}</h4>
          <div className="memory-filters">
            {MEMORY_ORIGIN_FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                className={`settings-row__action${memoryFilter === filter.id ? " is-active" : ""}`}
                onClick={() => setMemoryFilter(filter.id)}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>
        {canEdit ? (
          <div className="memory-add">
            <input
              type="text"
              value={newMemory}
              onChange={(e) => setNewMemory(e.target.value)}
              maxLength={500}
              placeholder="Add a memory item…"
            />
            <button type="button" className="btn btn-primary" disabled={busy || !newMemory.trim()} onClick={() => void addMemory()}>
              Add
            </button>
          </div>
        ) : null}
        <div className="settings-list">
          {memories.length === 0 ? (
            <div className="settings-row">
              <span className="settings-row__hint">No memory items.</span>
            </div>
          ) : (
            memories.map((m) => {
              const learned = m.origin === "auto_chat";
              return (
                <div key={m.id} className={`settings-row-block${m.enabled ? "" : " is-dimmed"} settings-row-block--stacked`}>
                  <div className="settings-row">
                    <div className="settings-row__meta">
                      <span className="settings-row__title">{m.content}</span>
                      <span className="settings-row__hint">
                        <span className="settings-memory-chip">{learned ? "learned" : "manual"}</span>
                        {learned && m.category ? <span className="settings-memory-chip">{m.category}</span> : null}
                        {learned && m.sourceSessionId ? (
                          <Link to={`/projects/${encodeURIComponent(projectId)}?session=${encodeURIComponent(m.sourceSessionId)}`}>
                            {m.sourceSessionTitle || "Source chat"}
                          </Link>
                        ) : null}
                      </span>
                    </div>
                    {canEdit ? (
                      <div className="settings-row__trail">
                        <button type="button" className="settings-row__action" onClick={() => void toggleMemory(m)}>
                          {m.enabled ? "Disable" : "Enable"}
                        </button>
                        <button
                          type="button"
                          className="settings-row__action settings-row__action--danger"
                          onClick={() => void deleteMemory(m.id)}
                        >
                          Delete
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </div>
        {memoryTotal > memories.length ? (
          <p className="form-hint">
            Showing the {memories.length} most recently updated of {memoryTotal} facts.
          </p>
        ) : null}
        {canEdit ? (
          <div className="memory-danger-actions">
            <button
              type="button"
              className="settings-row__action settings-row__action--danger"
              disabled={busy}
              onClick={() => void deleteAllLearned()}
            >
              Delete all learned facts
            </button>
          </div>
        ) : null}
      </section>

      <section className="settings-section">
        <h3>Grounding</h3>
        <p className="form-hint">Control what the model may read on each project chat turn.</p>
        <label className="form-field form-field--inline">
          <input
            type="checkbox"
            checked={useProjectResources}
            onChange={(e) => setUseProjectResources(e.target.checked)}
            disabled={!canEdit}
          />
          <span>Use project resources (Knowledge files) in chat</span>
        </label>
        <label className="form-field form-field--inline">
          <input
            type="checkbox"
            checked={useGrantedMemory}
            onChange={(e) => setUseGrantedMemory(e.target.checked)}
            disabled={!canEdit}
          />
          <span>Use granted memory from other projects</span>
        </label>
      </section>

      <section className="settings-section">
        <h3>Cross-project memory grants</h3>
        <p className="form-hint">Memory grants let this project read memory items from another project where you are also an Owner.</p>
        {canEdit ? (
          <div className="memory-add">
            <select
              className="input"
              value={grantSourceId}
              onChange={(e) => setGrantSourceId(e.target.value)}
            >
              <option value="">Select a source project…</option>
              {grantable.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <button type="button" className="btn btn-primary" disabled={busy || !grantSourceId} onClick={() => void addGrant()}>
              Grant
            </button>
          </div>
        ) : null}
        {canEdit && grantable.length === 0 ? (
          <p className="form-hint">You need to be Owner of another project to create a grant.</p>
        ) : null}
        <ul className="grant-list">
          {grants.map((g) => (
            <li key={g.id} className="grant-item">
              <span>{g.sourceProjectName ?? g.sourceProjectId}</span>
              {canEdit ? (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void revokeGrant(g.sourceProjectId)}>
                  Revoke
                </button>
              ) : null}
            </li>
          ))}
          {grants.length === 0 ? <li className="empty-state">No active grants.</li> : null}
        </ul>
      </section>

      {canEdit ? (
        <section className="settings-section">
          <h3>Configuration history</h3>
          <p className="form-hint">Restore creates a new revision from a previous snapshot. Old versions are never mutated.</p>
          <table className="data-table">
            <thead>
              <tr><th>Revision</th><th>Created</th><th></th></tr>
            </thead>
            <tbody>
              {versions.map((v) => {
                const active = config?.configVersionId === v.id;
                return (
                  <tr key={v.id}>
                    <td>{v.revision}{active ? " (active)" : ""}</td>
                    <td>{v.createdAt ? new Date(v.createdAt).toLocaleString() : "—"}</td>
                    <td>
                      {!active ? (
                        <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void restoreVersion(v)}>
                          Restore
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
              {versions.length === 0 ? <tr><td colSpan={3} className="empty-state">No saved versions yet.</td></tr> : null}
            </tbody>
          </table>
        </section>
      ) : null}

      {canEdit ? (
        <div className="settings-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void saveConfig()}>
            {busy ? "Saving…" : "Save settings"}
          </button>
        </div>
      ) : null}
    </div>
  );
}



function MembersTab({
  projectId,
  canManageMembers,
  myRole,
}: {
  projectId: string;
  canManageMembers: boolean;
  myRole: ProjectRole | null;
}) {
  const [members, setMembers] = useState<ProjectMemberRecord[]>([]);
  const [invitations, setInvitations] = useState<InvitationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [invOpen, setInvOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<InvitableUser[]>([]);
  const [selectedUser, setSelectedUser] = useState<InvitableUser | null>(null);
  const [newRole, setNewRole] = useState<ProjectRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [invRole, setInvRole] = useState<ProjectRole>("viewer");
  const [lastToken, setLastToken] = useState<string | null>(null);
  const [notifyUserId, setNotifyUserId] = useState("");
  const [invitees, setInvitees] = useState<InvitableUser[]>([]);
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
    } catch (err) {
      setError(formatApiError(err));
    } finally {
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
        if (active) setInvitees(res.users);
      })
      .catch(() => {
        if (active) setInvitees([]);
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
        if (active) setResults(res.users);
      })
      .catch(() => {
        if (active) setResults([]);
      });
    return () => {
      active = false;
    };
  }, [addOpen, search, projectId]);

  async function addUser() {
    if (!selectedUser) return;
    setBusy(true);
    setError("");
    try {
      await addMember(projectId, selectedUser.id, newRole);
      setAddOpen(false);
      setSelectedUser(null);
      setSearch("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(userId: number, role: ProjectRole) {
    try {
      await updateMemberRole(projectId, userId, role);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function removeUser(userId: number) {
    try {
      await removeMember(projectId, userId);
      await load();
    } catch (err) {
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
      if (inv.emailWarning) setEmailWarning(inv.emailWarning);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function revokeInv(id: string) {
    try {
      await revokeInvitation(projectId, id);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div className="project-tab-body">
      {error ? <div className="flash flash-error">{error}</div> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}

      {canManageMembers ? (
        <div className="members-actions">
          <button type="button" className="btn btn-primary" onClick={() => setAddOpen(true)}>
            Add member
          </button>
          <button type="button" className="btn" onClick={() => { setInvOpen(true); setLastToken(null); }}>
            Create invitation link
          </button>
        </div>
      ) : null}

      <h3>Members</h3>
      <table className="data-table">
        <thead>
          <tr><th>User</th><th>Role</th><th></th></tr>
        </thead>
        <tbody>
          {members.map((m) => {
            const canEditRow =
              canManageMembers &&
              m.role !== "primary_owner" &&
              (m.role !== "owner" || isPrimaryOwnerRole(myRole));
            return (
            <tr key={`${m.projectId}:${m.userId}`}>
              <td>{m.displayName ?? m.username ?? `User #${m.userId}`}</td>
              <td>
                {canEditRow ? (
                  <select value={m.role} onChange={(e) => void changeRole(m.userId, e.target.value as ProjectRole)}>
                    {roleOptions.map((r) => <option key={r} value={r}>{projectRoleLabel(r)}</option>)}
                  </select>
                ) : (
                  <span>{projectRoleLabel(m.role)}</span>
                )}
              </td>
              <td>
                {canEditRow ? (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void removeUser(m.userId)}>
                    Remove
                  </button>
                ) : null}
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Invitation links</h3>
      <table className="data-table">
        <thead>
          <tr><th>Role</th><th>Uses</th><th>Expires</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {invitations.map((inv) => (
            <tr key={inv.id}>
              <td>{projectRoleLabel(inv.role)}</td>
              <td>{inv.useCount} / {inv.maxUses}</td>
              <td>{inv.expiresAt ?? "—"}</td>
              <td>
                {inv.isRevoked ? "revoked" : inv.isExpired ? "expired" : inv.isExhausted ? "exhausted" : "active"}
              </td>
              <td>
                {canManageMembers && !inv.isRevoked ? (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void revokeInv(inv.id)}>
                    Revoke
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
          {invitations.length === 0 ? <tr><td colSpan={5} className="empty-state">No invitation links.</td></tr> : null}
        </tbody>
      </table>

      <Modal
        open={addOpen}
        title="Add member"
        onClose={() => {
          setAddOpen(false);
          setSearch("");
          setSelectedUser(null);
        }}
        panelClassName="modal-panel--project-form"
      >
        <label className="form-field">
          <span>Search users</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            placeholder="Type a username…"
          />
        </label>
        {search.trim() ? (
          <div className="user-search-results">
            {results.map((u) => (
              <button
                key={u.id}
                type="button"
                className={`user-search-row${selectedUser?.id === u.id ? " user-search-row--selected" : ""}`}
                onClick={() => setSelectedUser(u)}
              >
                <span>{u.displayName ?? u.username}</span>
                {u.displayName && u.username && u.displayName !== u.username ? (
                  <small>{u.username}</small>
                ) : null}
              </button>
            ))}
            {results.length === 0 ? <p className="user-search-empty">No users found.</p> : null}
          </div>
        ) : null}
        {selectedUser ? (
          <div className="user-search-selected">
            <span>{selectedUser.displayName ?? selectedUser.username}</span>
            <small>Selected</small>
          </div>
        ) : search.trim() ? null : (
          <p className="form-hint">Type a username, then choose a role.</p>
        )}
        <label className="form-field">
          <span>Role</span>
          <select value={newRole} onChange={(e) => setNewRole(e.target.value as ProjectRole)}>
            {roleOptions.map((r) => <option key={r} value={r}>{projectRoleLabel(r)}</option>)}
          </select>
        </label>
        <div className="dialog-actions">
          <button type="button" className="btn btn-primary" disabled={!selectedUser || busy} onClick={() => void addUser()}>
            {busy ? "Adding…" : "Add"}
          </button>
          <button
            type="button"
            className="btn btn-ghost dialog-actions-cancel"
            onClick={() => {
              setAddOpen(false);
              setSearch("");
              setSelectedUser(null);
            }}
          >
            Cancel
          </button>
        </div>
      </Modal>

      <Modal
        open={invOpen}
        title="Create invitation link"
        onClose={() => { setInvOpen(false); setLastToken(null); setEmailWarning(""); setNotifyUserId(""); }}
        panelClassName="modal-panel--project-form"
      >
        <label className="form-field">
          <span>Role</span>
          <select value={invRole} onChange={(e) => setInvRole(e.target.value as ProjectRole)}>
            <option value="contributor">Contributor</option>
            <option value="viewer">Viewer</option>
          </select>
        </label>
        <p className="form-hint">Invitation links never grant Owner or Primary Owner.</p>
        <label className="form-field">
          <span>Email invite to (optional)</span>
          <select value={notifyUserId} onChange={(e) => setNotifyUserId(e.target.value)}>
            <option value="">Don't email — copy the link</option>
            {invitees.map((u) => (
              <option key={u.id} value={String(u.id)}>
                {u.displayName ?? u.username}
              </option>
            ))}
          </select>
        </label>
        <p className="form-hint">If SMTP is not configured, the link is still created.</p>
        {emailWarning ? <div className="flash">{emailWarning}</div> : null}
        {lastToken ? (
          <div className="invitation-token-box">
            <p>Share this link (shown once):</p>
            <code>{window.location.origin}/app/projects/invite?token={lastToken}</code>
          </div>
        ) : null}
        <div className="dialog-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void createInv()}>
            {busy ? "Creating…" : "Create link"}
          </button>
          <button
            type="button"
            className="btn btn-ghost dialog-actions-cancel"
            onClick={() => { setInvOpen(false); setLastToken(null); setEmailWarning(""); setNotifyUserId(""); }}
          >
            Close
          </button>
        </div>
      </Modal>
    </div>
  );
}
