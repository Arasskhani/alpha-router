import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { flattenNav, isNavGrouped, type NavItem, type NavSection } from "../nav/types";

const OPEN_SECTIONS_STORAGE_KEY = "nitro.admin.sidebar.openSections";
const LEGACY_COLLAPSED_STORAGE_KEY = "nitro.admin.sidebar.collapsed";

type Props = {
  nav: NavItem[] | NavSection[];
  className?: string;
  linkClassName?: string;
  onNavigate?: () => void;
};

function NavLink({
  item,
  active,
  className,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  className?: string;
  onNavigate?: () => void;
}) {
  return (
    <Link
      to={item.to}
      className={active ? `active ${className ?? ""}`.trim() : className}
      onClick={onNavigate}
    >
      {item.label}
    </Link>
  );
}

/** true = expanded; missing key = expanded (default open). */
function loadOpenSections(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(OPEN_SECTIONS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, boolean>;
      }
    }
    const legacy = localStorage.getItem(LEGACY_COLLAPSED_STORAGE_KEY);
    if (legacy) {
      const collapsed = JSON.parse(legacy) as Record<string, unknown>;
      const open: Record<string, boolean> = {};
      for (const [title, value] of Object.entries(collapsed)) {
        if (value === true) open[title] = false;
      }
      return open;
    }
  } catch {
    /* ignore */
  }
  return {};
}

function sectionIsOpen(openSections: Record<string, boolean>, title: string): boolean {
  return openSections[title] !== false;
}

export default function SidebarNav({ nav, className = "", linkClassName, onNavigate }: Props) {
  const loc = useLocation();
  const pathname = loc.pathname.replace(/\/$/, "") || "/";
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(() => loadOpenSections());
  const userClosedRef = useRef<Set<string>>(new Set());

  const isActive = (to: string) => {
    const target = to.replace(/\/$/, "") || "/";
    return pathname === target;
  };

  const grouped = isNavGrouped(nav);

  useEffect(() => {
    localStorage.setItem(OPEN_SECTIONS_STORAGE_KEY, JSON.stringify(openSections));
  }, [openSections]);

  useEffect(() => {
    if (!grouped) return;
    setOpenSections((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const section of nav) {
        const hasActive = section.items.some((item) => isActive(item.to));
        if (!hasActive || userClosedRef.current.has(section.title)) continue;
        if (next[section.title] === false) {
          next[section.title] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // Only re-expand for the active route when the path changes — not when toggling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, grouped]);

  function toggleSection(title: string, event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    setOpenSections((prev) => {
      const currentlyOpen = sectionIsOpen(prev, title);
      const nextOpen = !currentlyOpen;
      if (nextOpen) {
        userClosedRef.current.delete(title);
      } else {
        userClosedRef.current.add(title);
      }
      return { ...prev, [title]: nextOpen };
    });
  }

  if (!grouped) {
    return (
      <nav className={className}>
        {nav.map((n) => (
          <NavLink
            key={n.to}
            item={n}
            active={isActive(n.to)}
            className={linkClassName}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
    );
  }

  const navClass = [className, "sidebar-nav--grouped"].filter(Boolean).join(" ");

  return (
    <nav className={navClass}>
      {nav.map((section) => {
        const isOpen = sectionIsOpen(openSections, section.title);
        const sectionActive = section.items.some((item) => isActive(item.to));
        return (
          <div
            key={section.title}
            className={`sidebar-nav-section${section.muted ? " sidebar-nav-section--muted" : ""}${
              isOpen ? "" : " sidebar-nav-section--collapsed"
            }${sectionActive ? " sidebar-nav-section--active" : ""}`}
          >
            <button
              type="button"
              className="sidebar-nav-section-toggle"
              onClick={(e) => toggleSection(section.title, e)}
              aria-expanded={isOpen}
              aria-controls={`sidebar-section-${section.title.replace(/\s+/g, "-").toLowerCase()}`}
            >
              <span className="sidebar-nav-section-title">{section.title}</span>
              <span className="sidebar-nav-section-chevron" aria-hidden>
                {isOpen ? "▾" : "▸"}
              </span>
            </button>
            {isOpen ? (
              <div
                id={`sidebar-section-${section.title.replace(/\s+/g, "-").toLowerCase()}`}
                className="sidebar-nav-section-items"
              >
                {section.items.map((n) => (
                  <NavLink
                    key={n.to}
                    item={n}
                    active={isActive(n.to)}
                    className={linkClassName}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}

/** Flat list for mobile drawer title search etc. */
export { flattenNav };
