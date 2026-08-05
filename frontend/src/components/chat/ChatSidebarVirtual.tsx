import { useEffect, useRef, type ReactNode } from "react";

type VirtualSidebarListProps = {
  items: { id: string; node: ReactNode }[];
  className?: string;
  onLoadMore?: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
};

/** Sidebar session list — plain list; parent `.alpha-router-sidebar-body` handles scrolling. */
export default function VirtualSidebarList({
  items,
  className,
  onLoadMore,
  hasMore,
  loadingMore,
}: VirtualSidebarListProps) {
  const sentinelRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !onLoadMore || !hasMore || loadingMore) return;
    const root = sentinel.closest(".alpha-router-sidebar-body");
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) onLoadMore();
      },
      { root, rootMargin: "120px", threshold: 0 },
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  }, [onLoadMore, hasMore, loadingMore, items.length]);

  return (
    <ul className={`alpha-router-history${className ? ` ${className}` : ""}`}>
      {items.map((item) => item.node)}
      {hasMore ? (
        <li ref={sentinelRef} className="alpha-router-history-empty" aria-hidden="true">
          {loadingMore ? "Loading…" : ""}
        </li>
      ) : null}
    </ul>
  );
}
