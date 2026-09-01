import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatApiError } from "../api";
import Modal from "../components/Modal";
import { createProject, listProjects, projectRoleLabel, } from "../lib/projectsApi";
const INITIAL_CREATE = {
    open: false,
    name: "",
    description: "",
    visibility: "private",
    busy: false,
    error: "",
};
export default function ProjectsPage() {
    const [mine, setMine] = useState([]);
    const [explore, setExplore] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [exploreQ, setExploreQ] = useState("");
    const [create, setCreate] = useState(INITIAL_CREATE);
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
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
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
        }
        catch (err) {
            setCreate((s) => ({ ...s, error: formatApiError(err) }));
        }
        finally {
            setCreate((s) => ({ ...s, busy: false }));
        }
    }
    return (_jsxs("div", { className: "admin-page", children: [_jsxs("header", { className: "admin-page-header", children: [_jsx("h1", { children: "Projects" }), _jsx("div", { className: "admin-page-actions", children: _jsx("button", { type: "button", className: "btn btn-primary", onClick: () => setCreate({ ...INITIAL_CREATE, open: true }), children: "+ New project" }) })] }), flash ? _jsx("div", { className: "flash flash-success", children: flash }) : null, error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, _jsxs("section", { className: "projects-section", children: [_jsx("h2", { children: "My projects" }), mine.filter((p) => p.status === "active").length === 0 && !loading ? (_jsx("p", { className: "empty-state", children: "You are not a member of any active project yet." })) : (_jsx("div", { className: "project-grid", children: mine
                            .filter((p) => p.status === "active")
                            .map((p) => (_jsx(ProjectCard, { project: p }, p.id))) }))] }), mine.some((p) => p.status === "archived") ? (_jsxs("section", { className: "projects-section", children: [_jsx("h2", { children: "Archived" }), _jsx("div", { className: "project-grid", children: mine
                            .filter((p) => p.status === "archived")
                            .map((p) => (_jsx(ProjectCard, { project: p }, p.id))) })] })) : null, mine.some((p) => p.status === "deletion_pending") ? (_jsxs("section", { className: "projects-section", children: [_jsx("h2", { children: "Pending deletion" }), _jsx("p", { className: "form-hint", children: "These projects are marked for deletion. Owners can restore them or purge now from the workspace." }), _jsx("div", { className: "project-grid", children: mine
                            .filter((p) => p.status === "deletion_pending")
                            .map((p) => (_jsx(ProjectCard, { project: p }, p.id))) })] })) : null, _jsxs("section", { className: "projects-section", children: [_jsx("h2", { children: "Explore public projects" }), _jsx("div", { className: "projects-explore-toolbar", children: _jsx("input", { type: "search", placeholder: "Search public projects\u2026", value: exploreQ, onChange: (e) => setExploreQ(e.target.value), className: "input" }) }), explore.length === 0 && !loading ? (_jsx("p", { className: "empty-state", children: "No public projects to explore." })) : (_jsx("div", { className: "project-grid", children: explore.map((p) => (_jsx(ProjectCard, { project: p }, p.id))) }))] }), _jsx(Modal, { open: create.open, title: "New project", onClose: () => setCreate(INITIAL_CREATE), panelClassName: "modal-panel--project-form", children: _jsxs("form", { onSubmit: (e) => {
                        e.preventDefault();
                        void submitCreate();
                    }, children: [_jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Name" }), _jsx("input", { type: "text", value: create.name, onChange: (e) => setCreate((s) => ({ ...s, name: e.target.value })), maxLength: 255, required: true, autoFocus: true })] }), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Description" }), _jsx("textarea", { value: create.description, onChange: (e) => setCreate((s) => ({ ...s, description: e.target.value })), maxLength: 4000, rows: 3 })] }), _jsxs("label", { className: "form-field", children: [_jsx("span", { children: "Visibility" }), _jsxs("select", { value: create.visibility, onChange: (e) => setCreate((s) => ({ ...s, visibility: e.target.value })), children: [_jsx("option", { value: "private", children: "Private (members only)" }), _jsx("option", { value: "public", children: "Public (all authenticated users)" })] })] }), create.visibility === "public" ? (_jsx("p", { className: "form-hint form-hint--warning", children: "Public projects are readable by every authenticated user. Only make a project public if its content and resources are safe to share organization-wide." })) : null, create.error ? _jsx("p", { className: "form-error", children: create.error }) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn btn-primary", disabled: create.busy || !create.name.trim(), children: create.busy ? "Creating…" : "Create" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setCreate(INITIAL_CREATE), children: "Cancel" })] })] }) })] }));
}
function statusLabel(status) {
    if (status === "archived")
        return "archived";
    if (status === "deletion_pending")
        return "pending deletion";
    return null;
}
function ProjectCard({ project }) {
    const status = statusLabel(project.status);
    return (_jsxs(Link, { to: `/app/projects/${project.id}`, className: "project-card", children: [_jsxs("div", { className: "project-card-header", children: [_jsx("span", { className: "project-card-name", children: project.name }), _jsxs("span", { className: "project-card-badges", children: [status ? (_jsx("span", { className: `project-card-badge project-card-badge--${project.status}`, children: status })) : null, _jsx("span", { className: `project-card-badge project-card-badge--${project.visibility}`, children: project.visibility })] })] }), project.description ? (_jsx("p", { className: "project-card-desc", children: project.description })) : (_jsx("p", { className: "project-card-desc project-card-desc--empty", children: "No description" })), _jsx("div", { className: "project-card-footer", children: project.myRole ? _jsx("span", { className: "project-card-role", children: projectRoleLabel(project.myRole) }) : null })] }));
}
