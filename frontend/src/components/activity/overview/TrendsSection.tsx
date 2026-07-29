import { useState } from "react";
import type { OverviewFocus, TrendsDimension, TrendsMetric } from "../types";
import OverviewStackedCard from "./OverviewStackedCard";
import TrendsTrendingList, { TrendsMetricSelect } from "./TrendsTrendingList";

type Props = {
  title: string;
  focus: OverviewFocus;
  dimension: TrendsDimension;
  onExplore: (focus: OverviewFocus) => void;
};

export default function TrendsSection({ title, focus, dimension, onExplore }: Props) {
  const [metric, setMetric] = useState<TrendsMetric>("spend");

  return (
    <section className="trends-section">
      <h2 className="trends-section__title">{title}</h2>
      <div className="trends-section__grid">
        <div className="trends-section__metric">
          <TrendsMetricSelect metric={metric} onMetricChange={setMetric} />
        </div>
        <OverviewStackedCard
          title="Spend over time"
          focus={focus}
          data={dimension.spend_over_time}
          valuePrefix="spend_"
          valueKind="spend"
          onExplore={onExplore}
          chartHeight={240}
        />
        <TrendsTrendingList
          itemsByMetric={dimension.trending}
          focus={focus}
          onExplore={onExplore}
          metric={metric}
        />
      </div>
    </section>
  );
}
