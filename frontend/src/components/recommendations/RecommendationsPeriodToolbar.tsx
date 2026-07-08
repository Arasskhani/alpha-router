import { useMemo } from "react";

export const PRESET_PERIODS = [7, 14, 30, 60, 90] as const;
export type PresetPeriod = (typeof PRESET_PERIODS)[number];
export const MIN_CUSTOM_RANGE_DAYS = 3;

export type PeriodSelection =
  | { mode: "preset"; days: PresetPeriod }
  | { mode: "custom"; from: string; to: string };

export function inclusiveDayCount(from: string, to: string): number {
  if (!from || !to) return 0;
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0;
  return Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
}

export function validateCustomRange(from: string, to: string): string | null {
  if (!from || !to) return "Select both start and end dates.";
  const days = inclusiveDayCount(from, to);
  if (days <= 0) return "End date must be on or after start date.";
  if (days < MIN_CUSTOM_RANGE_DAYS) {
    return `Select at least a ${MIN_CUSTOM_RANGE_DAYS}-day range so we can estimate recommendations.`;
  }
  return null;
}

export function buildRecommendationsQuery(selection: PeriodSelection): string {
  const q = new URLSearchParams();
  if (selection.mode === "preset") {
    q.set("period_days", String(selection.days));
  } else {
    q.set("from", selection.from);
    q.set("to", selection.to);
  }
  return q.toString();
}

type Props = {
  selection: PeriodSelection;
  onPresetChange: (days: PresetPeriod) => void;
  onCustomFromChange: (from: string) => void;
  onCustomToChange: (to: string) => void;
  onApplyCustom: () => void;
  customDraftFrom: string;
  customDraftTo: string;
  customError: string | null;
  disabled?: boolean;
};

export default function RecommendationsPeriodToolbar({
  selection,
  onPresetChange,
  onCustomFromChange,
  onCustomToChange,
  onApplyCustom,
  customDraftFrom,
  customDraftTo,
  customError,
  disabled = false,
}: Props) {
  const customPreviewDays = useMemo(
    () => inclusiveDayCount(customDraftFrom, customDraftTo),
    [customDraftFrom, customDraftTo],
  );

  return (
    <div className="recommendations-period-toolbar">
      <div className="recommendations-period-toolbar__presets" role="group" aria-label="Time range">
        {PRESET_PERIODS.map((days) => (
          <button
            key={days}
            type="button"
            className={`recommendations-period-btn${
              selection.mode === "preset" && selection.days === days ? " recommendations-period-btn--active" : ""
            }`}
            onClick={() => onPresetChange(days)}
            disabled={disabled}
          >
            {days} days
          </button>
        ))}
      </div>

      <div className="recommendations-period-toolbar__custom">
        <span className="recommendations-period-toolbar__custom-label">Custom range</span>
        <label className="recommendations-period-date">
          <span className="sr-only">Start date</span>
          <input
            type="date"
            value={customDraftFrom}
            onChange={(e) => onCustomFromChange(e.target.value)}
            disabled={disabled}
            aria-label="Start date"
          />
        </label>
        <span className="recommendations-period-toolbar__sep">to</span>
        <label className="recommendations-period-date">
          <span className="sr-only">End date</span>
          <input
            type="date"
            value={customDraftTo}
            min={customDraftFrom || undefined}
            onChange={(e) => onCustomToChange(e.target.value)}
            disabled={disabled}
            aria-label="End date"
          />
        </label>
        <button
          type="button"
          className="btn btn-ghost recommendations-period-apply"
          onClick={onApplyCustom}
          disabled={disabled || !customDraftFrom || !customDraftTo}
        >
          Apply
        </button>
        {selection.mode === "custom" ? (
          <span className="recommendations-period-active-badge">
            {selection.from} → {selection.to}
          </span>
        ) : null}
      </div>

      {customError ? <p className="recommendations-period-error">{customError}</p> : null}
      {!customError && customDraftFrom && customDraftTo && customPreviewDays > 0 && customPreviewDays < MIN_CUSTOM_RANGE_DAYS ? (
        <p className="recommendations-period-hint muted-text">
          Minimum range: {MIN_CUSTOM_RANGE_DAYS} days (currently {customPreviewDays}).
        </p>
      ) : null}
    </div>
  );
}
