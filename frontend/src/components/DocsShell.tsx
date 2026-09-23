import { ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { usePhoneLayout } from "../hooks/useMediaQuery";

type DocNavItem = { id: string; title: string };
export type DocNavGroup = [string, DocNavItem[]];
export type DocSectionDef = { id: string; title: string; group?: string; content: ReactNode };

type Props = {
  sidebarLabel: string;
  searchPlaceholder?: string;
  sections: DocSectionDef[];
  navGroups: DocNavGroup[];
};

/**
 * The User Manual and the Admin Guide: a contents column beside the text.
 *
 * On a phone the two columns do not fit (the text was left 110 of 390
 * pixels), so the text takes the whole width, the search sits in a bar above
 * it with a Contents button, and the contents list opens from that button as
 * a side sheet over the page (a modal dialog, above the topbar like the other
 * sheets). The sheet, the text and the search field keep their place in the
 * tree at every width, so turning a tablet keeps the reading position.
 */
export default function DocsShell({
  sidebarLabel,
  searchPlaceholder = "Search…",
  sections,
  navGroups,
}: Props) {
  const location = useLocation();
  const phone = usePhoneLayout();
  const [activeId, setActiveId] = useState(sections[0]?.id ?? "");
  const [query, setQuery] = useState("");
  const [contentsOpen, setContentsOpen] = useState(false);
  const contentsId = useId();
  const contentsButtonRef = useRef<HTMLButtonElement>(null);
  const contentsRef = useRef<HTMLElement>(null);

  // Leaving the phone layout puts the contents back beside the text; an open
  // sheet would otherwise come back by itself on the next rotation.
  const [wasPhone, setWasPhone] = useState(phone);
  if (wasPhone !== phone) {
    setWasPhone(phone);
    setContentsOpen(false);
  }
  const sheetOpen = phone && contentsOpen;

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

  // The sheet is modal: Escape closes it, Tab goes round inside it.
  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContentsOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const stops = [...(contentsRef.current?.querySelectorAll<HTMLElement>("button") ?? [])];
      if (stops.length === 0) return;
      event.preventDefault();
      const at = stops.indexOf(document.activeElement as HTMLElement);
      const step = event.shiftKey ? -1 : 1;
      stops[at < 0 ? 0 : (at + step + stops.length) % stops.length].focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sheetOpen]);

  // Focus goes to the section being read when the sheet opens, and back to
  // the Contents button when it closes.
  const sheetWasOpen = useRef(false);
  useEffect(() => {
    if (sheetOpen) {
      const sheet = contentsRef.current;
      (sheet?.querySelector<HTMLElement>(".docs-nav-link.active") ?? sheet?.querySelector<HTMLElement>(".docs-nav-link"))?.focus();
    } else if (sheetWasOpen.current) {
      contentsButtonRef.current?.focus({ preventScroll: true });
    }
    sheetWasOpen.current = sheetOpen;
  }, [sheetOpen]);

  function scrollTo(id: string) {
    setActiveId(id);
    setContentsOpen(false);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const search = (
    <input
      type="search"
      className="docs-search"
      placeholder={searchPlaceholder}
      aria-label={searchPlaceholder.replace(/…$/, "")}
      value={query}
      onChange={(e) => setQuery(e.target.value)}
    />
  );

  return (
    <div className="docs-shell">
      {phone ? (
        <div className="docs-phone-bar">
          <button
            ref={contentsButtonRef}
            type="button"
            className="docs-contents-btn"
            aria-haspopup="dialog"
            aria-expanded={sheetOpen}
            aria-controls={contentsId}
            onClick={() => setContentsOpen(true)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />
            </svg>
            Contents
          </button>
          {search}
        </div>
      ) : null}
      <aside
        ref={contentsRef}
        id={contentsId}
        className={`docs-sidebar${phone ? " docs-sidebar--drawer" : ""}${sheetOpen ? " is-open" : ""}`}
        {...(sheetOpen ? { role: "dialog", "aria-modal": true, "aria-label": `${sidebarLabel} contents` } : {})}
      >
        <div className="docs-sidebar-head">
          <span className="docs-sidebar-label">{sidebarLabel}</span>
          {phone ? (
            <button
              type="button"
              className="docs-contents-close"
              aria-label="Close contents"
              onClick={() => setContentsOpen(false)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
              </svg>
            </button>
          ) : (
            search
          )}
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
                  aria-current={activeId === item.id ? "location" : undefined}
                  onClick={() => scrollTo(item.id)}
                >
                  {item.title}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      {sheetOpen ? <div className="docs-contents-backdrop" aria-hidden onClick={() => setContentsOpen(false)} /> : null}

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
