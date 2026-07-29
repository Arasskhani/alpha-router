import type { ActivityExplore, ExploreControls } from "../../types";
import ExploreChartCard from "./ExploreChartCard";
import ExploreTable from "./ExploreTable";
import ExploreToolbar from "./ExploreToolbar";

type Props = {
  explore: ActivityExplore;
  controls: ExploreControls;
  onControlsChange: (patch: Partial<ExploreControls>, clearFocus?: boolean) => void;
  onDownloadPdf?: (mode: "current" | "summary") => void;
};

export default function ActivityExplorePanel({
  explore,
  controls,
  onControlsChange,
  onDownloadPdf,
}: Props) {
  return (
    <div className="activity-explore">
      <ExploreToolbar controls={controls} onChange={onControlsChange} />
      <ExploreChartCard
        explore={explore}
        controls={controls}
        onChange={onControlsChange}
        onDownloadPdf={onDownloadPdf}
      />
      <ExploreTable explore={explore} />
    </div>
  );
}
