import type { ActivityOverview, OverviewFocus } from "../types";
import OverviewKpiRow from "./OverviewKpiRow";
import OverviewStackedCard from "./OverviewStackedCard";
import OverviewTopList from "./OverviewTopList";

type Props = {
  overview: ActivityOverview;
  onExplore: (focus: OverviewFocus) => void;
};

export default function ActivityOverviewPanel({ overview, onExplore }: Props) {
  return (
    <div className="activity-overview">
      <OverviewKpiRow kpis={overview.kpis} />

      <div className="overview-lists-row">
        <OverviewTopList
          title="Top Users"
          focus="users"
          items={overview.top_users}
          emptyLabel="No user usage in this period"
          onExplore={onExplore}
        />
        <OverviewTopList
          title="Top Apps"
          focus="apps"
          items={overview.top_apps}
          emptyLabel="No app usage in this period"
          onExplore={onExplore}
        />
      </div>

      <OverviewStackedCard
        title="Usage by model"
        focus="usage_by_model"
        data={overview.usage_by_model}
        valuePrefix="spend_"
        valueKind="spend"
        onExplore={onExplore}
        chartHeight={260}
      />

      <OverviewStackedCard
        title="Request volume by model"
        focus="request_volume"
        data={overview.request_volume_by_model}
        valuePrefix="requests_"
        valueKind="requests"
        onExplore={onExplore}
      />

      <div className="overview-charts-row">
        <OverviewStackedCard
          title="Token breakdown"
          focus="token_breakdown"
          data={overview.token_breakdown}
          valueKind="tokens"
          onExplore={onExplore}
        />
        <OverviewStackedCard
          title="Prompt token caching"
          focus="prompt_caching"
          data={overview.prompt_caching}
          valueKind="tokens"
          onExplore={onExplore}
        />
      </div>
    </div>
  );
}
