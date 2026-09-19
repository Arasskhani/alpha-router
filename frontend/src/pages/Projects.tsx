import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatApiError } from "../api";
import Modal from "../components/Modal";
import {
  createProject,
  listProjects,
  projectRoleLabel,
  type ProjectRecord,
  type ProjectVisibility,
} from "../lib/projectsApi";

type CreateState = {
  open: boolean;
  name: string;
  description: string;
  visibility: ProjectVisibility;
  busy: boolean;
  error: string;
};

const INITIAL_CREATE: CreateState = {
  open: false,
  name: "",
  description: "",
  visibility: "private",
  busy: false,
  error: "",
};

export default function ProjectsPage() {
  const [mine, setMine] = useState<ProjectRecord[]>([]);
  const [explore, setExplore] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exploreQ, setExploreQ] = useState("");
  const [create, setCreate] = useState<CreateState>(INITIAL_CREATE);
  const [flash, setFlash] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [myRes, exRes] = await Promise.all([
        listProjects("mine", { limit: 100 }),
        listProjects("explore", { limit: 100, q: exploreQ || undefined }),
      ]);
      setMine(myRes.projects);
      setExplore(exRes.projects);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [exploreQ]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitCreate() {
    setCreate((s) => ({ ...s, busy: true, error: "" }));
    try {
      const project = await createProject({
        name: create.name.trim(),
        description: create.description.trim() || null,
        visibility: create.visibility,
      });
      setMine((prev) => [project, ...prev]);
      setCreate(INITIAL_CREATE);
      setFlash(`Project “${project.name}” created.`);
    } catch (err) {
      setCreate((s) => ({ ...s, error: formatApiError(err) }));
    } finally {
      setCreate((s) => ({ ...s, busy: false }));
    }
  }

  return (
    <div className="admin-page">
      <header className="admin-page-header">
        <h1>Projects</h1>
        <div className="admin-page-actions">
          <button type="button" className="btn btn-primary" onClick={() => setCreate({ ...INITIAL_CREATE, open: true })}>
            + New project
          </button>
        </div>
      </header>

      {flash ? <div className="flash flash-success">{flash}</div> : null}
      {error ? <div className="flash flash-error">{error}</div> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}

      <section className="projects-section">
        <h2>My projects</h2>
        {mine.filter((p) => p.status === "active").length === 0 && !loading ? (
          <p className="empty-state">You are not a member of any active project yet.</p>
        ) : (
          <div className="project-grid">
            {mine
              .filter((p) => p.status === "active")
              .map((p) => (
                <ProjectCard key={p.id} project={p} />
              ))}
          </div>
        )}
      </section>

      {mine.some((p) => p.status === "archived") ? (
        <section className="projects-section">
          <h2>Archived</h2>
          <div className="project-grid">
            {mine
              .filter((p) => p.status === "archived")
              .map((p) => (
                <ProjectCard key={p.id} project={p} />
              ))}
          </div>
        </section>
      ) : null}

      {mine.some((p) => p.status === "deletion_pending") ? (
        <section className="projects-section">
          <h2>Pending deletion</h2>
          <p className="form-hint">
            These projects are marked for deletion. Owners can restore them or purge now from the workspace.
          </p>
          <div className="project-grid">
            {mine
              .filter((p) => p.status === "deletion_pending")
              .map((p) => (
                <ProjectCard key={p.id} project={p} />
              ))}
          </div>
        </section>
      ) : null}

      <section className="projects-section">
        <h2>Explore public projects</h2>
        <div className="projects-explore-toolbar">
          <input
            type="search"
            placeholder="Search public projects…"
            value={exploreQ}
            onChange={(e) => setExploreQ(e.target.value)}
            className="input"
          />
        </div>
        {explore.length === 0 && !loading ? (
          <p className="empty-state">No public projects to explore.</p>
        ) : (
          <div className="project-grid">
            {explore.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </section>

      <Modal
        open={create.open}
        title="New project"
        onClose={() => setCreate(INITIAL_CREATE)}
        panelClassName="modal-panel--project-form"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submitCreate();
          }}
        >
          <label className="form-field">
            <span>Name</span>
            <input
              type="text"
              value={create.name}
              onChange={(e) => setCreate((s) => ({ ...s, name: e.target.value }))}
              maxLength={255}
              required
              autoFocus
            />
          </label>
          <label className="form-field">
            <span>Description</span>
            <textarea
              value={create.description}
              onChange={(e) => setCreate((s) => ({ ...s, description: e.target.value }))}
              maxLength={4000}
              rows={3}
            />
          </label>
          <label className="form-field">
            <span>Visibility</span>
            <select
              value={create.visibility}
              onChange={(e) => setCreate((s) => ({ ...s, visibility: e.target.value as ProjectVisibility }))}
            >
              <option value="private">Private (members only)</option>
              <option value="public">Public (all authenticated users)</option>
            </select>
          </label>
          {create.visibility === "public" ? (
            <p className="form-hint form-hint--warning">
              Public projects are readable by every authenticated user. Only make a project public if its content and resources are safe to share organization-wide.
            </p>
          ) : null}
          {create.error ? <p className="form-error" role="alert">{create.error}</p> : null}
          <div className="dialog-actions">
            <button type="submit" className="btn btn-primary" disabled={create.busy || !create.name.trim()}>
              {create.busy ? "Creating…" : "Create"}
            </button>
            <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setCreate(INITIAL_CREATE)}>
              Cancel
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function statusLabel(status: ProjectRecord["status"]): string | null {
  if (status === "archived") return "archived";
  if (status === "deletion_pending") return "pending deletion";
  return null;
}

function ProjectCard({ project }: { project: ProjectRecord }) {
  const status = statusLabel(project.status);
  return (
    <Link to={`/app/projects/${project.id}`} className="project-card">
      <div className="project-card-header">
        <span className="project-card-name">{project.name}</span>
        <span className="project-card-badges">
          {status ? (
            <span className={`project-card-badge project-card-badge--${project.status}`}>
              {status}
            </span>
          ) : null}
          <span className={`project-card-badge project-card-badge--${project.visibility}`}>
            {project.visibility}
          </span>
        </span>
      </div>
      {project.description ? (
        <p className="project-card-desc">{project.description}</p>
      ) : (
        <p className="project-card-desc project-card-desc--empty">No description</p>
      )}
      <div className="project-card-footer">
        {project.myRole ? <span className="project-card-role">{projectRoleLabel(project.myRole)}</span> : null}
      </div>
    </Link>
  );
}
