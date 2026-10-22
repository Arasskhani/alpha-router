import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { NavIcon } from "./icons/navIcons";
import { isNavGrouped, type NavItem, type NavSection, type TicketBadgeKey } from "../nav/types";
import { STORAGE_KEYS } from "../lib/brand";
import { badgeText, useTicketBadges, type TicketBadges } from "../hooks/useTicketBadges";

type Props = {
  nav: NavItem[] | NavSection[];
  className?: string;
  linkClassName?: string;
  onNavigate?: () => void;
};

/** What a screen reader hears after the item's name. */
const BADGE_WORDS: Record<TicketBadgeKey, (count: number) => string> = {
  support: (n) => `${n} ${n === 1 ? "ticket" : "tickets"} with a new reply`,
  tickets: (n) => `${n} ${n === 1 ? "ticket waits" : "tickets wait"} for staff`,
};

/** The count an item shows; 0 without a badge. */
export function navBadgeCount(item: NavItem, badges: TicketBadges): number {
  if (!item.badge) return 0;
  return item.badge === "support" ? badges.support : badges.tickets;
}

/** ", 2 tickets with a new reply" for an item whose name is an aria-label; "" without a count. */
export function navBadgeWords(item: NavItem, badges: TicketBadges): string {
  const count = navBadgeCount(item, badges);
  return item.badge && count > 0 ? `, ${BADGE_WORDS[item.badge](count)}` : "";
}

export function NavBadge({ item, badges }: { item: NavItem; badges: TicketBadges }) {
  const count = navBadgeCount(item, badges);
  if (!item.badge || count <= 0) return null;
  const urgent = item.badge === "tickets" && badges.ticketsUrgent;
  return (
    <span className={`nav-count-badge${urgent ? " nav-count-badge--urgent" : ""}`}>
      <span aria-hidden="true">{badgeText(count)}</span>
      <span className="sr-only">, {BADGE_WORDS[item.badge](count)}</span>
    </span>
  );
}

/** The badge keys a menu draws, for useTicketBadges. */
export function navBadgeKeys(items: NavItem[]): TicketBadgeKey[] {
  return [...new Set(items.flatMap((item) => (item.badge ? [item.badge] : [])))];
}

function NavLink({
  item,
  active,
  className,
  onNavigate,
  badges,
}: {
  item: NavItem;
  active: boolean;
  className?: string;
  onNavigate?: () => void;
  badges: TicketBadges;
}) {
  return (
    <Link
      to={item.to}
      className={active ? `active ${className ?? ""}`.trim() : className}
      onClick={onNavigate}
    >
      {item.icon ? <NavIcon name={item.icon} /> : null}
      <span className="sidebar-nav-label">{item.label}</span>
      <NavBadge item={item} badges={badges} />
    </Link>
  );
}

/** true = expanded; missing key = expanded (default open). */
function loadOpenSections(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.adminSidebarOpenSections);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, boolean>;
      }
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

  const grouped = isNavGrouped(nav);
  const allItems: NavItem[] = grouped ? nav.flatMap((section) => section.items) : nav;
  const prefixMatched = new Set(allItems.filter((item) => item.matchPrefix).map((item) => item.to));
  const badges = useTicketBadges(navBadgeKeys(allItems));

  const isActive = (to: string) => {
    const target = to.replace(/\/$/, "") || "/";
    return pathname === target || (prefixMatched.has(to) && pathname.startsWith(`${target}/`));
  };

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.adminSidebarOpenSections, JSON.stringify(openSections));
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
            badges={badges}
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
                    badges={badges}
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
;
