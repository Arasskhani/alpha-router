import { useCallback, useMemo, useRef, useState } from "react";

import { useDismiss, useReturnFocus } from "./AssignMenu";
import { PRIORITIES, PRIORITY_LABELS, STATUSES, statusLabel } from "../../lib/tickets";
import { initials, type OverviewFilterKey, type OverviewFilters } from "../../lib/ticketsAdmin";

type Option = { key: string; label: string; avatar?: boolean };

type Props = {
  value: OverviewFilters;
  departments: string[];
  assignees: { id: number; name: string }[];
  categories: string[];
  onChange: (patch: Partial<OverviewFilters>) => void;
  onClear: () => void;
};

const CATEGORIES: { key: OverviewFilterKey; label: string; plural: string; all: string }[] = [
  { key: "assignee", label: "Assignee", plural: "Assignees", all: "All assignees" },
  { key: "department", label: "Department", plural: "Departments", all: "All departments" },
  { key: "priority", label: "Priority", plural: "Priorities", all: "All priorities" },
  { key: "category", label: "Category", plural: "Categories", all: "All categories" },
  { key: "status", label: "Status", plural: "Statuses", all: "All statuses" },
];

function IconFilter() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M4 6h16M7 12h10M10 18h4" />
    </svg>
  );
}

function IconChevron() {
  return (
    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

function IconSearch() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

/**
 * The Overview's filters, in the look of Activity's filter menu (the same
 * classes): categories on the right, their values in a flyout to the left.
 */
export default function TicketFilterMenu({ value, departments, assignees, categories, onChange, onClear }: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<OverviewFilterKey>("assignee");
  const [categoryQuery, setCategoryQuery] = useState("");
  const [valueQuery, setValueQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  // A click outside or Escape closes it; focus goes back to the button.
  useDismiss(ref, open, close);
  useReturnFocus(open, triggerRef);

  const activeCount = CATEGORIES.reduce((n, c) => n + (value[c.key] ? 1 : 0), 0);

  function toggle() {
    setOpen((v) => !v);
    setCategoryQuery("");
    setValueQuery("");
  }

  function choose(key: OverviewFilterKey) {
    if (key !== active) setValueQuery("");
    setActive(key);
  }

  const options = useMemo((): Option[] => {
    switch (active) {
      case "assignee":
        return [
          ...assignees.map((a) => ({ key: String(a.id), label: a.name, avatar: true })),
          { key: "none", label: "Unassigned" },
        ];
      case "department":
        return departments.map((d) => ({ key: d, label: d, avatar: true }));
      case "priority":
        return PRIORITIES.map((p) => ({ key: p, label: PRIORITY_LABELS[p] }));
      case "category":
        return categories.map((c) => ({ key: c, label: c }));
      case "status":
        return STATUSES.map((s) => ({ key: s, label: statusLabel(s, "staff") }));
      default:
        return [];
    }
  }, [active, assignees, departments, categories]);

  const meta = CATEGORIES.find((c) => c.key === active)!;
  const filtered = useMemo(() => {
    const q = valueQuery.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, valueQuery]);
  const visibleCategories = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase();
    return q ? CATEGORIES.filter((c) => c.label.toLowerCase().includes(q)) : CATEGORIES;
  }, [categoryQuery]);
  const selected = value[active];

  function pick(key: string) {
    onChange({ [active]: key });
    setOpen(false);
  }

  return (
    <div className="activity-filter-menu" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        className={`activity-icon-btn${open ? " activity-icon-btn--active" : ""}${activeCount ? " activity-icon-btn--badge" : ""}`}
        onClick={toggle}
        aria-label="Filters"
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Filters"
      >
        <IconFilter />
      </button>
      {open ? (
        <div className="activity-filter-popover" role="dialog" aria-label="Ticket filters">
          <div className="activity-filter-flyout card">
            <div className="activity-filter-mode" role="group" aria-label="Filter mode">
              <button type="button" className="activity-filter-mode__btn is-active" aria-pressed="true">
                Include
              </button>
              <button type="button" className="activity-filter-mode__btn" aria-pressed="false" disabled title="Coming soon">
                Exclude
              </button>
            </div>
            <div className="activity-filter-flyout__search">
              <span className="activity-filter-flyout__search-icon">
                <IconSearch />
              </span>
              <input
                type="text"
                className="activity-filter-flyout__search-input"
                placeholder={`Search ${meta.plural.toLowerCase()}`}
                aria-label={`Search ${meta.plural.toLowerCase()}`}
                value={valueQuery}
                onChange={(e) => setValueQuery(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
              <span className="activity-filter-flyout__count muted-text">
                {filtered.length} {filtered.length === 1 ? meta.label.toLowerCase() : meta.plural.toLowerCase()}
              </span>
            </div>
            <div className="activity-filter-flyout__section">
              <div className="activity-filter-flyout__section-head">
                <span>{meta.plural}</span>
                {selected ? (
                  <button type="button" className="activity-filter-flyout__clear" onClick={() => onChange({ [active]: "" })}>
                    Clear
                  </button>
                ) : null}
              </div>
              <ul className="activity-filter-flyout__list" role="listbox" aria-label={meta.plural}>
                {!valueQuery.trim() ? (
                  <li>
                    <button
                      type="button"
                      role="option"
                      aria-selected={!selected}
                      className={`activity-filter-flyout__item${!selected ? " is-active" : ""}`}
                      onClick={() => pick("")}
                    >
                      <span className="activity-filter-flyout__item-text">
                        <span className="activity-filter-flyout__item-label">{meta.all}</span>
                      </span>
                    </button>
                  </li>
                ) : null}
                {filtered.length === 0 ? (
                  <li className="activity-filter-flyout__empty muted-text">
                    {valueQuery.trim() ? "No matches" : "None in this period"}
                  </li>
                ) : (
                  filtered.map((opt) => (
                    <li key={opt.key}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={selected === opt.key}
                        className={`activity-filter-flyout__item${selected === opt.key ? " is-active" : ""}`}
                        onClick={() => pick(opt.key)}
                      >
                        {opt.avatar ? (
                          <span className="activity-filter-avatar" aria-hidden>
                            {initials(opt.label)}
                          </span>
                        ) : null}
                        <span className="activity-filter-flyout__item-text">
                          <span className="activity-filter-flyout__item-label">{opt.label}</span>
                        </span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
          <div className="activity-filter-primary card">
            <input
              type="text"
              className="activity-filter-primary__search"
              placeholder="Search filters…"
              aria-label="Search filter categories"
              value={categoryQuery}
              onChange={(e) => setCategoryQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <ul className="activity-filter-primary__list">
              {visibleCategories.map((cat) => (
                <li key={cat.key}>
                  <button
                    type="button"
                    className={`activity-filter-primary__item${active === cat.key ? " is-active" : ""}`}
                    onMouseEnter={() => choose(cat.key)}
                    onFocus={() => choose(cat.key)}
                    onClick={() => choose(cat.key)}
                  >
                    <span>{cat.label}</span>
                    <span className="activity-filter-primary__meta">
                      {value[cat.key] ? <span className="activity-filter-dot" aria-hidden /> : null}
                      <IconChevron />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {activeCount ? (
              <button type="button" className="activity-filter-primary__clear" onClick={onClear}>
                Clear all filters
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
