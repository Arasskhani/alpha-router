import type { PickableTab } from "./otherTabs";

type Props = {
  tabs: PickableTab[] | null;
  /** The row the arrow keys are on. */
  active: number;
  /** Why a tab cannot go with this question, if it cannot. */
  blockFor: (tab: PickableTab) => string | null;
  onPick: (tab: PickableTab) => void;
  onClose: () => void;
};

/** The other tabs of this window, to add one to the next question. */
export default function TabPicker({ tabs, active, blockFor, onPick, onClose }: Props) {
  return (
    <div className="tab-picker" role="listbox" aria-label="Tabs to add">
      <div className="tab-picker__head">
        <span>Add a tab</span>
        <button type="button" className="btn btn--quiet tab-picker__close" aria-label="Close the tab list" onClick={onClose}>
          ×
        </button>
      </div>
      {tabs === null ? (
        <p className="tab-picker__note">Loading tabs…</p>
      ) : tabs.length === 0 ? (
        <p className="tab-picker__note">No other tab here can be added.</p>
      ) : (
        tabs.map((tab, index) => {
          const blocked = blockFor(tab);
          return (
            <button
              key={tab.tabId}
              type="button"
              role="option"
              aria-selected={index === active}
              className={`tab-picker__item${index === active ? " tab-picker__item--active" : ""}`}
              disabled={Boolean(blocked)}
              title={blocked ?? tab.url}
              // Keep the composer's focus, so @ typing goes on after a pick.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onPick(tab)}
            >
              <span className="tab-picker__title">{tab.title}</span>
              <span className="tab-picker__site">{blocked ?? tab.target.host}</span>
            </button>
          );
        })
      )}
    </div>
  );
}
