import ModelName from "../ModelName";
import { MODEL_KIND_LABELS, type CatalogModel } from "../../lib/modelCatalog";
import {
  formatContextLength,
  formatModelTitle,
  formatPerMTokenPrice,
  formatReleasedDate,
} from "../../lib/modelCatalogFormat";

type Props = {
  models: CatalogModel[];
  selectedIds: number[];
  onToggleSelect: (id: number) => void;
  onToggleEnabled: (id: number, enabled: boolean) => void;
};

export default function ModelsBrowseView({
  models,
  selectedIds,
  onToggleSelect,
  onToggleEnabled,
}: Props) {
  return (
    <div className="models-browse-list">
      {models.map((m) => {
        const kinds = m.kinds?.length ? m.kinds : [];
        return (
          <article
            key={m.id}
            className={`models-browse-card card${m.enabled ? "" : " models-browse-card--off"}`}
          >
            <div className="models-browse-card__top">
              <label className="models-browse-card__check">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(m.id)}
                  onChange={() => onToggleSelect(m.id)}
                  aria-label={`Select ${m.external_id}`}
                />
              </label>
              <div className="models-browse-card__head">
                <h3 className="models-browse-card__title">
                  <ModelName
                    modelId={m.external_id}
                    label={formatModelTitle(m)}
                    provider={m.provider_author}
                    size={18}
                  />
                </h3>
                {kinds.length > 0 ? (
                  <div className="models-browse-card__tags">
                    {kinds.map((k) => (
                      <span key={k} className="models-browse-card__tag">
                        {MODEL_KIND_LABELS[k]}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className={`btn btn-sm model-toggle-btn${m.enabled ? " model-toggle-btn--on" : ""}`}
                onClick={() => onToggleEnabled(m.id, m.enabled)}
              >
                {m.enabled ? "ON" : "OFF"}
              </button>
            </div>

            {m.description ? (
              <p className="models-browse-card__desc">{m.description}</p>
            ) : (
              <p className="models-browse-card__desc muted-text">No description from provider yet. Re-sync connection.</p>
            )}

            <footer className="models-browse-card__meta">
              <span>
                by <span className="models-browse-card__provider">{m.provider_author || "—"}</span>
              </span>
              {m.released_at ? <span>{formatReleasedDate(m.released_at)}</span> : null}
              {m.context_length != null ? <span>{formatContextLength(m.context_length)}</span> : null}
              {m.input_cost_per_1k != null ? (
                <span>{formatPerMTokenPrice(m.input_cost_per_1k, "input")}</span>
              ) : null}
              {m.output_cost_per_1k != null ? (
                <span>{formatPerMTokenPrice(m.output_cost_per_1k, "output")}</span>
              ) : null}
            </footer>
          </article>
        );
      })}
    </div>
  );
}
