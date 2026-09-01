import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
/** Sidebar session list — plain list; parent `.alpha-router-sidebar-body` handles scrolling. */
export default function VirtualSidebarList({ items, className, onLoadMore, hasMore, loadingMore, }) {
    const sentinelRef = useRef(null);
    useEffect(() => {
        const sentinel = sentinelRef.current;
        if (!sentinel || !onLoadMore || !hasMore || loadingMore)
            return;
        const root = sentinel.closest(".alpha-router-sidebar-body");
        const obs = new IntersectionObserver((entries) => {
            if (entries[0]?.isIntersecting)
                onLoadMore();
        }, { root, rootMargin: "120px", threshold: 0 });
        obs.observe(sentinel);
        return () => obs.disconnect();
    }, [onLoadMore, hasMore, loadingMore, items.length]);
    return (_jsxs("ul", { className: `alpha-router-history${className ? ` ${className}` : ""}`, children: [items.map((item) => item.node), hasMore ? (_jsx("li", { ref: sentinelRef, className: "alpha-router-history-empty", "aria-hidden": "true", children: loadingMore ? "Loading…" : "" })) : null] }));
}
