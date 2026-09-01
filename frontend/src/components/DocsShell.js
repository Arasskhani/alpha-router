import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
export default function DocsShell({ sidebarLabel, searchPlaceholder = "Search…", sections, navGroups, }) {
    const location = useLocation();
    const [activeId, setActiveId] = useState(sections[0]?.id ?? "");
    const [query, setQuery] = useState("");
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return sections;
        return sections.filter((s) => s.title.toLowerCase().includes(q) || s.id.replace(/-/g, " ").includes(q));
    }, [query, sections]);
    useEffect(() => {
        const hashId = location.hash.replace(/^#/, "");
        if (!hashId)
            return;
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
            .filter(Boolean);
        const observer = new IntersectionObserver((entries) => {
            const visible = entries
                .filter((e) => e.isIntersecting)
                .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
            if (visible[0]?.target?.id)
                setActiveId(visible[0].target.id);
        }, { rootMargin: "-80px 0px -60% 0px", threshold: [0, 0.25, 0.5] });
        nodes.forEach((n) => observer.observe(n));
        return () => observer.disconnect();
    }, [sections]);
    function scrollTo(id) {
        setActiveId(id);
        document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    return (_jsxs("div", { className: "docs-shell", children: [_jsxs("aside", { className: "docs-sidebar", children: [_jsxs("div", { className: "docs-sidebar-head", children: [_jsx("span", { className: "docs-sidebar-label", children: sidebarLabel }), _jsx("input", { type: "search", className: "docs-search", placeholder: searchPlaceholder, value: query, onChange: (e) => setQuery(e.target.value) })] }), _jsx("nav", { className: "docs-nav", children: navGroups.map(([group, items]) => (_jsxs("div", { className: "docs-nav-group", children: [_jsx("div", { className: "docs-nav-group-title", children: group }), items.map((item) => (_jsx("button", { type: "button", className: `docs-nav-link${activeId === item.id ? " active" : ""}`, onClick: () => scrollTo(item.id), children: item.title }, item.id)))] }, group))) })] }), _jsxs("article", { className: "docs-main", children: [filtered.map((section) => (_jsx("section", { id: section.id, className: "docs-section", children: section.content }, section.id))), filtered.length === 0 && _jsx("p", { className: "docs-muted", children: "No sections match your search." })] })] }));
}
export function buildDocNavGroups(sections) {
    return Array.from(sections.reduce((map, s) => {
        const g = s.group ?? "Guide";
        if (!map.has(g))
            map.set(g, []);
        map.get(g).push({ id: s.id, title: s.title });
        return map;
    }, new Map()));
}
