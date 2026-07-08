import { ReactNode, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

export type DocNavItem = { id: string; title: string };
export type DocNavGroup = [string, DocNavItem[]];
export type DocSectionDef = { id: string; title: string; group?: string; content: ReactNode };

type Props = {
  sidebarLabel: string;
  searchPlaceholder?: string;
  sections: DocSectionDef[];
  navGroups: DocNavGroup[];
};

export default function DocsShell({
  sidebarLabel,
  searchPlaceholder = "Search…",
  sections,
  navGroups,
}: Props) {
  const location = useLocation();
  const [activeId, setActiveId] = useState(sections[0]?.id ?? "");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sections;
    return sections.filter(
      (s) => s.title.toLowerCase().includes(q) || s.id.replace(/-/g, " ").includes(q),
    );
  }, [query, sections]);

  useEffect(() => {
    const hashId = location.hash.replace(/^#/, "");
    if (!hashId) return;
    const t = window.setTimeout(() => {
      const el = document.getElementById(hashId);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        setActiveId(hashId);
      }
    }, 80);
    return () => window.clearTimeout(t);
  }, [location.pathname, location.hash]);

  useEffect(() => {
    const nodes = sections
      .map((s) => document.getElementById(s.id))
      .filter(Boolean) as HTMLElement[];

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]?.target?.id) setActiveId(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -60% 0px", threshold: [0, 0.25, 0.5] },
    );

    nodes.forEach((n) => observer.observe(n));
    return () => observer.disconnect();
  }, [sections]);

  function scrollTo(id: string) {
    setActiveId(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="docs-shell">
      <aside className="docs-sidebar">
        <div className="docs-sidebar-head">
          <span className="docs-sidebar-label">{sidebarLabel}</span>
          <input
            type="search"
            className="docs-search"
            placeholder={searchPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <nav className="docs-nav">
          {navGroups.map(([group, items]) => (
            <div key={group} className="docs-nav-group">
              <div className="docs-nav-group-title">{group}</div>
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`docs-nav-link${activeId === item.id ? " active" : ""}`}
                  onClick={() => scrollTo(item.id)}
                >
                  {item.title}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <article className="docs-main">
        {filtered.map((section) => (
          <section key={section.id} id={section.id} className="docs-section">
            {section.content}
          </section>
        ))}
        {filtered.length === 0 && <p className="docs-muted">No sections match your search.</p>}
      </article>
    </div>
  );
}

export function buildDocNavGroups(sections: DocSectionDef[]): DocNavGroup[] {
  return Array.from(
    sections.reduce((map, s) => {
      const g = s.group ?? "Guide";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push({ id: s.id, title: s.title });
      return map;
    }, new Map<string, DocNavItem[]>()),
  );
}
