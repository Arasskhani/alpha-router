import { Link } from "react-router-dom";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import RecommendationsPeriodToolbar, {
  buildRecommendationsQuery,
  type PeriodSelection,
  type PresetPeriod,
  validateCustomRange,
} from "../../components/recommendations/RecommendationsPeriodToolbar";
import RecommendationsView, { type RecommendationsPayload } from "../../components/recommendations/RecommendationsView";
import { getSessionUser } from "../../lib/session";

function defaultCustomTo(): string {
  return new Date().toISOString().slice(0, 10);
}

function defaultCustomFrom(): string {
  const d = new Date();
  d.setDate(d.getDate() - 29);
  return d.toISOString().slice(0, 10);
}

export default function Recommendations() {
  const user = getSessionUser();
  const [data, setData] = useState<RecommendationsPayload | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [selection, setSelection] = useState<PeriodSelection>({ mode: "preset", days: 30 });
  const [customDraftFrom, setCustomDraftFrom] = useState(defaultCustomFrom);
  const [customDraftTo, setCustomDraftTo] = useState(defaultCustomTo);
  const [customError, setCustomError] = useState<string | null>(null);

  const backLink = useMemo(() => {
    const home = user?.role === "admin" ? "/admin/chat" : "/app/chat";
    return { to: home, label: "← Chat" };
  }, [user?.role]);

  const load = useCallback(async (period: PeriodSelection) => {
    setLoading(true);
    setErr("");
    try {
      const payload = await api<RecommendationsPayload>(
        `/api/user/recommendations?${buildRecommendationsQuery(period)}`,
      );
      setData(payload);
    } catch (e) {
      setData(null);
      setErr(e instanceof Error ? e.message : "Failed to load recommendations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(selection);
  }, [load, selection]);

  function handlePresetChange(days: PresetPeriod) {
    setCustomError(null);
    setSelection({ mode: "preset", days });
  }

  function handleApplyCustom() {
    const validation = validateCustomRange(customDraftFrom, customDraftTo);
    if (validation) {
      setCustomError(validation);
      return;
    }
    setCustomError(null);
    setSelection({ mode: "custom", from: customDraftFrom, to: customDraftTo });
  }

  return (
    <div className="recommendations-page">
      <header className="activity-page-head recommendations-page__head">
        <div>
          <p className="activity-back-link">
            <Link to={backLink.to}>{backLink.label}</Link>
          </p>
          <h1>Recommendations</h1>
        </div>
        <RecommendationsPeriodToolbar
          selection={selection}
          onPresetChange={handlePresetChange}
          onCustomFromChange={(from) => {
            setCustomDraftFrom(from);
            setCustomError(null);
          }}
          onCustomToChange={(to) => {
            setCustomDraftTo(to);
            setCustomError(null);
          }}
          onApplyCustom={handleApplyCustom}
          customDraftFrom={customDraftFrom}
          customDraftTo={customDraftTo}
          customError={customError}
          disabled={loading}
        />
      </header>

      {loading && !data ? <p className="muted-text">Loading…</p> : null}
      {err ? <p className="error-text">{err}</p> : null}
      {data ? <RecommendationsView data={data} loading={loading} /> : null}
    </div>
  );
}
