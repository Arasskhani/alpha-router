import type { ExploreControls, ExploreGroup, ExploreMetric, ExploreRankBy, ExploreRollup, ExploreTopMode } from "../../types";
import ExploreMenu from "./ExploreMenu";
import {
  EXPLORE_GROUP_OPTIONS,
  EXPLORE_METRIC_OPTIONS,
  EXPLORE_ROLLUP_OPTIONS,
  EXPLORE_TOP_N_OPTIONS,
  groupLabel,
} from "./explorePresets";

type Props = {
  controls: ExploreControls;
  hiddenGroups?: ExploreGroup[];
  onChange: (patch: Partial<ExploreControls>, clearFocus?: boolean) => void;
};

export default function ExploreToolbar({ controls, hiddenGroups = [], onChange }: Props) {
  const groupOptions = EXPLORE_GROUP_OPTIONS.filter(
    (o) => o.value === controls.group || !hiddenGroups.includes(o.value),
  );
  const subgroupOptions = groupOptions.filter(
    (o) => o.value !== "none" && o.value !== controls.group,
  );

  return (
    <div className="explore-toolbar">
      <div className="explore-toolbar__left">
        <ExploreMenu
          value={controls.metric}
          options={EXPLORE_METRIC_OPTIONS}
          onChange={(v) => onChange({ metric: v as ExploreMetric }, true)}
          searchable
          searchPlaceholder="Metric"
          ariaLabel="Explore metric"
        />
        <span className="explore-toolbar__by">by</span>
        <ExploreMenu
          value={controls.group}
          options={groupOptions}
          onChange={(v) => {
            const group = v as ExploreGroup;
            const patch: Partial<ExploreControls> = { group };
            if (controls.subgroup === group) patch.subgroup = "";
            onChange(patch, true);
          }}
          searchable
          searchPlaceholder="Group"
          ariaLabel="Group by"
        />
        <ExploreMenu
          value={controls.subgroup || ""}
          options={[{ value: "", label: "None" }, ...subgroupOptions]}
          onChange={(v) => onChange({ subgroup: (v || "") as ExploreGroup | "" }, true)}
          triggerLabel={controls.subgroup ? groupLabel(controls.subgroup) : "+ Subgroup"}
          searchable
          searchPlaceholder="Search"
          ariaLabel="Subgroup"
          className={!controls.subgroup ? "explore-menu--subgroup" : ""}
        />
        <ExploreMenu
          value={controls.rollup}
          options={EXPLORE_ROLLUP_OPTIONS}
          onChange={(v) => onChange({ rollup: v as ExploreRollup }, true)}
          triggerPrefix="Rollup: "
          ariaLabel="Rollup"
        />
        <div className="explore-toolbar__segmented">
          <ExploreMenu
            value={controls.topMode}
            options={[
              { value: "top", label: "Top" },
              { value: "bottom", label: "Bottom" },
            ]}
            onChange={(v) => onChange({ topMode: v as ExploreTopMode }, true)}
            ariaLabel="Top or bottom"
            className="explore-menu--segment"
          />
          <ExploreMenu
            value={String(controls.topN)}
            options={EXPLORE_TOP_N_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
            onChange={(v) => onChange({ topN: Number(v) }, true)}
            ariaLabel="Top N"
            className="explore-menu--segment"
          />
        </div>
        <ExploreMenu
          value={controls.rankBy}
          options={[
            { value: "metric", label: "Current metric" },
            { value: "requests", label: "Requests" },
          ]}
          onChange={(v) => onChange({ rankBy: v as ExploreRankBy }, true)}
          triggerPrefix="Rank by: "
          ariaLabel="Rank by"
        />
      </div>
    </div>
  );
}
