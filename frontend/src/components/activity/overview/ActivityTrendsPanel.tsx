import type { ActivityTrends, OverviewFocus } from "../types";
import TrendsSection from "./TrendsSection";

type Props = {
  trends: ActivityTrends;
  hideUsers?: boolean;
  hideApiKeys?: boolean;
  onExplore: (focus: OverviewFocus) => void;
};

export default function ActivityTrendsPanel({ trends, hideUsers = false, hideApiKeys = false, onExplore }: Props) {
  return (
    <div className="activity-trends">
      <TrendsSection title="Models" focus="trends_models" dimension={trends.models} onExplore={onExplore} />
      {hideUsers ? null : (
        <TrendsSection title="Users" focus="trends_users" dimension={trends.users} onExplore={onExplore} />
      )}
      {hideApiKeys ? null : (
        <TrendsSection title="API Keys" focus="trends_api_keys" dimension={trends.api_keys} onExplore={onExplore} />
      )}
      <TrendsSection title="Apps" focus="trends_apps" dimension={trends.apps} onExplore={onExplore} />
    </div>
  );
}
