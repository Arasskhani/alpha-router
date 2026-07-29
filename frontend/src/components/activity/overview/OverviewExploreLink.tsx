import type { OverviewFocus } from "../types";

type Props = {
  focus: OverviewFocus;
  onExplore: (focus: OverviewFocus) => void;
};

export default function OverviewExploreLink({ focus, onExplore }: Props) {
  return (
    <button type="button" className="overview-explore-link" onClick={() => onExplore(focus)}>
      Explore <span aria-hidden>›</span>
    </button>
  );
}
