import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { getCachedSession } from "../api";
import type { SessionRbac } from "../lib/rbac";
import { getSessionUser } from "../lib/session";
import { isProjectWorkspacePath, topbarShortcutsForSession } from "../lib/userPanelNav";
import { listProjects, projectRoleLabel, type ProjectRecord } from "../lib/projectsApi";
import type { CachedTheme } from "../lib/themeCache";
import { NavIcon } from "./icons/navIcons";
import UserProfile from "./UserProfile";

type Theme = CachedTheme;

type Props = {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
};

function ProjectsShortcut({
  to,
  label,
  active,
}: {
  to: string;
  label: string;
  active: boolean;
}) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<ProjectRecord[] | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void listProjects("recent", { limit: 8 })
      .then((data) => {
        if (!cancelled) setRecent(data.projects);
      })
      .catch(() => {
        if (!cancelled) setRecent([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <div className="topbar-shortcut-split" ref={wrapRef}>
      <NavLink
        to={to}
        className={`topbar-shortcut${active ? " topbar-shortcut--active" : ""}`}
      >
        <NavIcon name="projects" />
        <span>{label}</span>
      </NavLink>
      <button
        type="button"
        className={`topbar-shortcut-chevron${open || active ? " topbar-shortcut-chevron--active" : ""}`}
        aria-label="Recent projects"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((prev) => !prev);
        }}
      >
        <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden>
          <path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      {open ? (
        <div className="topbar-projects-menu" role="menu">
          {recent == null ? (
            <p className="topbar-projects-menu__empty">Loading…</p>
          ) : recent.length === 0 ? (
            <p className="topbar-projects-menu__empty">No recent projects</p>
          ) : (
            recent.map((project) => (
              <button
                key={project.id}
                type="button"
                role="menuitem"
                className="topbar-projects-menu__item"
                onClick={() => {
                  setOpen(false);
                  navigate(`/app/projects/${encodeURIComponent(project.id)}`);
                }}
              >
                <span className="topbar-projects-menu__name">{project.name}</span>
                {project.myRole ? (
                  <span className="topbar-projects-menu__role">{projectRoleLabel(project.myRole)}</span>
                ) : null}
              </button>
            ))
          )}
          <button
            type="button"
            className="topbar-projects-menu__item topbar-projects-menu__item--all"
            onClick={() => {
              setOpen(false);
              navigate(to);
            }}
          >
            All projects
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Top-bar actions: text shortcuts + faint profile menu (OpenRouter-style). */
export default function TopbarNav({ theme, onThemeChange }: Props) {
  const user = getSessionUser();
  const location = useLocation();
  if (!user) return null;

  const shortcuts = topbarShortcutsForSession(getCachedSession() as SessionRbac | null);
  const inProjectWorkspace = isProjectWorkspacePath(location.pathname);

  return (
    <div className="topbar-nav">
      <nav className="topbar-shortcuts" aria-label="Quick links">
        {shortcuts.map((item) => {
          if (item.icon === "projects") {
            const projectActive =
              inProjectWorkspace ||
              location.pathname === item.to ||
              location.pathname.startsWith(`${item.to}/`);
            return (
              <ProjectsShortcut
                key={item.to}
                to={item.to}
                label={item.label}
                active={projectActive}
              />
            );
          }
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => {
                const chatActive = item.icon === "chat" && inProjectWorkspace ? false : isActive;
                return `topbar-shortcut${chatActive ? " topbar-shortcut--active" : ""}`;
              }}
            >
              {item.icon ? <NavIcon name={item.icon} /> : null}
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
      <UserProfile theme={theme} onThemeChange={onThemeChange} />
    </div>
  );
}
