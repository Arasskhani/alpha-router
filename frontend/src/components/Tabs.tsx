import { useEffect, useRef, type KeyboardEvent } from "react";

import { scrollIntoStrip } from "../lib/scrollIntoStrip";

type TabItem<T extends string> = {
  id: T;
  label: React.ReactNode;
};

type Props<T extends string> = {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Names the tab list for assistive technology. */
  ariaLabel: string;
  /** Prefix for the tab and panel ids: `${idBase}-tab-${id}` / `${idBase}-panel-${id}`. */
  idBase: string;
  className?: string;
  tabClassName?: (id: T, active: boolean) => string;
};

/**
 * A real tab list: `role="tablist"` with `role="tab"` buttons, `aria-selected`,
 * roving focus (only the active tab is in the Tab order) and arrow-key
 * navigation, as the WAI-ARIA tabs pattern asks.
 *
 * Three screens used to draw tabs as a row of buttons with an "active" class.
 * They looked like tabs and were, to a keyboard or screen-reader user, a row
 * of unrelated buttons: nothing said which was selected, and Tab stopped on
 * every one of them.
 */
export default function Tabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  idBase,
  className = "tabs",
  tabClassName,
}: Props<T>) {
  const refs = useRef<Map<T, HTMLButtonElement>>(new Map());
  const listRef = useRef<HTMLDivElement>(null);

  // On a phone a tab list is one strip that scrolls sideways (styles.css);
  // the selected tab is kept in view when the page selects one by itself.
  useEffect(() => {
    scrollIntoStrip(listRef.current, refs.current.get(value));
  }, [value]);

  const focusAndSelect = (id: T) => {
    onChange(id);
    refs.current.get(id)?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = items.length - 1;
    let next: number | null = null;
    switch (event.key) {
      case "ArrowRight":
        next = index === last ? 0 : index + 1;
        break;
      case "ArrowLeft":
        next = index === 0 ? last : index - 1;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = last;
        break;
      default:
        return;
    }
    event.preventDefault();
    focusAndSelect(items[next].id);
  };

  return (
    <div ref={listRef} className={className} role="tablist" aria-label={ariaLabel}>
      {items.map((item, index) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              if (el) refs.current.set(item.id, el);
              else refs.current.delete(item.id);
            }}
            type="button"
            role="tab"
            id={`${idBase}-tab-${item.id}`}
            aria-selected={active}
            aria-controls={`${idBase}-panel-${item.id}`}
            tabIndex={active ? 0 : -1}
            className={tabClassName ? tabClassName(item.id, active) : `tab ${active ? "active" : ""}`}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

/** The panel a tab controls. Pairs ids with `Tabs` so the relationship is stated both ways. */
export function TabPanel<T extends string>({
  idBase,
  id,
  children,
  className,
}: {
  idBase: string;
  id: T;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div role="tabpanel" id={`${idBase}-panel-${id}`} aria-labelledby={`${idBase}-tab-${id}`} className={className}>
      {children}
    </div>
  );
}
