import { useEffect, useMemo, useRef, useState } from "react";
import ModelProviderIcon from "../ModelProviderIcon";
import type { ActivityFilterKey } from "./activityScope";
import type { ApiKeyFilterOption, FilterOption } from "./types";

export type { ActivityFilterKey };

type FilterValues = {
  model: string;
  user: string;
  app: string;
  status: string;
  apiKey: string;
};

type Props = {
  model: string;
  user: string;
  app: string;
  status: string;
  apiKey: string;
  models: FilterOption[];
  users: FilterOption[];
  apps: FilterOption[];
  apiKeys: ApiKeyFilterOption[];
  visibleKeys?: ActivityFilterKey[];
  onChange: (patch: Partial<FilterValues>) => void;
  onClear: () => void;
};

const CATEGORIES: { key: ActivityFilterKey; label: string }[] = [
  { key: "user", label: "User" },
  { key: "model", label: "Model" },
  { key: "apiKey", label: "API Key" },
  { key: "app", label: "App" },
  { key: "status", label: "Response status" },
];

const STATUS_OPTIONS: FilterOption[] = [
  { key: "", label: "All responses" },
  { key: "success", label: "Success" },
  { key: "fail", label: "Fail" },
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

function IconKey() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="8" cy="15" r="4" />
      <path d="M12 15h9v-2h-2v-2h-2v-2h-3" />
    </svg>
  );
}

function initials(label: string): string {
  const parts = label.trim().split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

/** OpenRouter-style cascading filter: primary list + left flyout. */
export default function ActivityFilterMenu({
  model,
  user,
  app,
  status,
  apiKey,
  models,
  users,
  apps,
  apiKeys,
  visibleKeys,
  onChange,
  onClear,
}: Props) {
  const [open, setOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState<ActivityFilterKey | null>("model");
  const [categoryQuery, setCategoryQuery] = useState("");
  const [valueQuery, setValueQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const values: FilterValues = { model, user, app, status, apiKey };
  const visibleCategories = useMemo(
    () => (visibleKeys?.length ? CATEGORIES.filter((c) => visibleKeys.includes(c.key)) : CATEGORIES),
    [visibleKeys],
  );
  const activeCount = visibleCategories.reduce((n, c) => n + (values[c.key] ? 1 : 0), 0);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) {
      setCategoryQuery("");
      setValueQuery("");
      setActiveCategory(visibleCategories[0]?.key ?? "model");
    }
  }, [open]);

  useEffect(() => {
    setValueQuery("");
  }, [activeCategory]);

  const filteredCategories = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase();
    if (!q) return visibleCategories;
    return visibleCategories.filter((c) => c.label.toLowerCase().includes(q));
  }, [categoryQuery, visibleCategories]);

  const optionsForCategory = useMemo((): FilterOption[] => {
    switch (activeCategory) {
      case "model":
        return models;
      case "user":
        return users;
      case "app":
        return apps;
      case "apiKey":
        return apiKeys;
      case "status":
        return STATUS_OPTIONS;
      default:
        return [];
    }
  }, [activeCategory, models, users, apps, apiKeys]);

  const filteredOptions = useMemo(() => {
    const q = valueQuery.trim().toLowerCase();
    if (!q) return optionsForCategory;
    return optionsForCategory.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        o.key.toLowerCase().includes(q) ||
        ("name" in o && String((o as ApiKeyFilterOption).name || "").toLowerCase().includes(q)) ||
        ("prefix" in o && String((o as ApiKeyFilterOption).prefix || "").toLowerCase().includes(q)),
    );
  }, [optionsForCategory, valueQuery]);

  const activeCategoryMeta = CATEGORIES.find((c) => c.key === activeCategory);
  const selectedKey = activeCategory ? values[activeCategory] : "";

  function pickValue(key: string) {
    if (!activeCategory) return;
    onChange({ [activeCategory]: key });
    setOpen(false);
  }

  function clearCategory() {
    if (!activeCategory) return;
    onChange({ [activeCategory]: "" });
  }

  const searchPlaceholder =
    activeCategory === "user"
      ? "Search for a user…"
      : activeCategory === "model"
        ? "Search models"
        : activeCategory === "apiKey"
          ? "Search API keys"
          : activeCategory === "app"
            ? "Search apps"
            : "Search…";

  return (
    <div className="activity-filter-menu" ref={ref}>
      <button
        type="button"
        className={`activity-icon-btn${open ? " activity-icon-btn--active" : ""}${activeCount ? " activity-icon-btn--badge" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label="Filters"
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Filters"
      >
        <IconFilter />
      </button>

      {open ? (
        <div className="activity-filter-popover" role="dialog" aria-label="Activity filters">
          {activeCategory && activeCategoryMeta ? (
            <div className="activity-filter-flyout card">
              <div className="activity-filter-mode" role="group" aria-label="Filter mode">
                <button type="button" className="activity-filter-mode__btn is-active" aria-pressed="true">
                  Include
                </button>
                <button
                  type="button"
                  className="activity-filter-mode__btn"
                  aria-pressed="false"
                  disabled
                  title="Coming soon"
                >
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
                  placeholder={searchPlaceholder}
                  value={valueQuery}
                  onChange={(e) => setValueQuery(e.target.value)}
                  aria-label={searchPlaceholder}
                  // eslint-disable-next-line jsx-a11y/no-autofocus -- a search menu the user just opened; focus belongs in its field
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                />
                <span className="activity-filter-flyout__count muted-text">
                  {filteredOptions.length} {activeCategoryMeta.label.toLowerCase()}
                  {filteredOptions.length === 1 ? "" : "s"}
                </span>
              </div>

              <div className="activity-filter-flyout__section">
                <div className="activity-filter-flyout__section-head">
                  <span>
                    {activeCategory === "status"
                      ? "Status"
                      : activeCategory === "apiKey"
                        ? "API Keys"
                        : `${activeCategoryMeta.label}s`}
                  </span>
                  {selectedKey ? (
                    <button type="button" className="activity-filter-flyout__clear" onClick={clearCategory}>
                      Clear
                    </button>
                  ) : null}
                </div>
                <ul className="activity-filter-flyout__list" role="listbox">
                  {filteredOptions.length === 0 ? (
                    <li className="activity-filter-flyout__empty muted-text">
                      {valueQuery.trim()
                        ? "No matches"
                        : "No usage in this period"}
                    </li>
                  ) : (
                    filteredOptions.map((opt) => {
                      const active = selectedKey === opt.key;
                      const keyOpt = opt as ApiKeyFilterOption;
                      return (
                        <li key={opt.key || "__all__"}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={active}
                            className={`activity-filter-flyout__item${active ? " is-active" : ""}`}
                            onClick={() => pickValue(opt.key)}
                          >
                            {activeCategory === "user" ? (
                              <span className="activity-filter-avatar" aria-hidden>
                                {initials(opt.label)}
                              </span>
                            ) : activeCategory === "apiKey" ? (
                              <span className="activity-filter-item-icon" aria-hidden>
                                <IconKey />
                              </span>
                            ) : activeCategory === "model" ? (
                              <span className="activity-filter-item-icon activity-filter-item-icon--model" aria-hidden>
                                <ModelProviderIcon modelId={opt.key} size={16} />
                              </span>
                            ) : null}
                            <span className="activity-filter-flyout__item-text">
                              <span className="activity-filter-flyout__item-label">
                                {keyOpt.name || opt.label}
                              </span>
                              {activeCategory === "apiKey" && keyOpt.prefix ? (
                                <span className="activity-filter-flyout__item-meta">{keyOpt.prefix}</span>
                              ) : null}
                            </span>
                          </button>
                        </li>
                      );
                    })
                  )}
                </ul>
              </div>
            </div>
          ) : null}

          <div className="activity-filter-primary card">
            <input
              type="text"
              className="activity-filter-primary__search"
              placeholder="Search filters…"
              value={categoryQuery}
              onChange={(e) => setCategoryQuery(e.target.value)}
              aria-label="Search filter categories"
              autoComplete="off"
              spellCheck={false}
            />
            <ul className="activity-filter-primary__list">
              {filteredCategories.map((cat) => {
                const hasValue = Boolean(values[cat.key]);
                return (
                  <li key={cat.key}>
                    <button
                      type="button"
                      className={`activity-filter-primary__item${activeCategory === cat.key ? " is-active" : ""}`}
                      onMouseEnter={() => setActiveCategory(cat.key)}
                      onFocus={() => setActiveCategory(cat.key)}
                      onClick={() => setActiveCategory(cat.key)}
                    >
                      <span>{cat.label}</span>
                      <span className="activity-filter-primary__meta">
                        {hasValue ? <span className="activity-filter-dot" aria-hidden /> : null}
                        <IconChevron />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {activeCount ? (
              <button
                type="button"
                className="activity-filter-primary__clear"
                onClick={() => {
                  onClear();
                }}
              >
                Clear all filters
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
