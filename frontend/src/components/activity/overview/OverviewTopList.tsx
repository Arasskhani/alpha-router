import { formatTokens } from "../formatters";
import type { OverviewFocus, OverviewListItem } from "../types";
import OverviewExploreLink from "./OverviewExploreLink";

type Props = {
  title: string;
  focus: OverviewFocus;
  items: OverviewListItem[];
  emptyLabel: string;
  onExplore: (focus: OverviewFocus) => void;
};

export default function OverviewTopList({ title, focus, items, emptyLabel, onExplore }: Props) {
  return (
    <article className="overview-top-list card">
      <header className="overview-card-head">
        <h3>{title}</h3>
        <OverviewExploreLink focus={focus} onExplore={onExplore} />
      </header>
      <ul className="overview-top-list__items">
        {items.map((item, idx) => (
          <li key={item.key}>
            <span className="overview-top-list__rank">{idx + 1}</span>
            <span className="overview-top-list__avatar" aria-hidden>
              {item.initials}
            </span>
            <span className="overview-top-list__meta">
              <span className="overview-top-list__name">{item.label}</span>
            </span>
            <span className="overview-top-list__value">{formatTokens(item.tokens)} tok</span>
          </li>
        ))}
        {items.length === 0 ? <li className="overview-top-list__empty muted-text">{emptyLabel}</li> : null}
      </ul>
    </article>
  );
}
