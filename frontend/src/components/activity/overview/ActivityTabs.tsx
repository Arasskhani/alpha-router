import type { ActivityTab } from "../types";

const TABS: { id: ActivityTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "trends", label: "Trends" },
  { id: "explore", label: "Explore" },
];

type Props = {
  value: ActivityTab;
  onChange: (tab: ActivityTab) => void;
};

export default function ActivityTabs({ value, onChange }: Props) {
  return (
    <nav className="activity-tabs" aria-label="Activity views">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`activity-tabs__btn${value === tab.id ? " is-active" : ""}`}
          aria-current={value === tab.id ? "page" : undefined}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
