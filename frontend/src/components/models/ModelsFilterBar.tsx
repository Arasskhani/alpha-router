import {
  MODEL_KIND_LABELS,
  MODEL_KIND_ORDER,
  type ModelKind,
  type CatalogModel,
  kindCounts,
} from "../../lib/modelCatalog";

function FilterIcon({ kind }: { kind: ModelKind }) {
  const common = { viewBox: "0 0 24 24", width: 18, height: 18, "aria-hidden": true as const };
  switch (kind) {
    case "text":
      return (
        <svg {...common}>
          <path fill="currentColor" d="M5 5h14v2H5V5zm0 4h10v2H5V9zm0 4h14v2H5v-2zm0 4h8v2H5v-2z" />
        </svg>
      );
    case "image":
      return (
        <svg {...common}>
          <path
            fill="currentColor"
            d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"
          />
        </svg>
      );
    case "embeddings":
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="2" fill="currentColor" />
          <circle cx="18" cy="6" r="2" fill="currentColor" />
          <circle cx="12" cy="18" r="2" fill="currentColor" />
          <path stroke="currentColor" strokeWidth="1.5" d="M8 6h8M7 8l4 8M17 8l-4 8" />
        </svg>
      );
    case "audio":
      return (
        <svg {...common}>
          <path
            fill="currentColor"
            d="M3 10v4c0 3.3 2.7 6 6 6h1v-8H9c-3.3 0-6 2.7-6 6zm14-2v8c0 2.2-1.8 4-4 4s-4-1.8-4-4V8c0-2.2 1.8-4 4-4s4 1.8 4 4z"
          />
        </svg>
      );
    case "video":
      return (
        <svg {...common}>
          <path
            fill="currentColor"
            d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"
          />
        </svg>
      );
    case "rerank":
      return (
        <svg {...common}>
          <path fill="currentColor" d="M8 6l-4 4 4 4V6zm8 0v8l4-4-4-4z" />
        </svg>
      );
    case "speech":
      return (
        <svg {...common}>
          <path
            fill="currentColor"
            d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1 3.08v2.42h2v-2.42c2.94-.47 5.2-2.94 5.2-5.66h-2c0 2.21-1.79 4-4 4s-4-1.79-4-4H3c0 2.72 2.26 5.19 5.2 5.66z"
          />
        </svg>
      );
    case "transcription":
      return (
        <svg {...common}>
          <path
            fill="currentColor"
            d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"
          />
        </svg>
      );
    default:
      return null;
  }
}

function AllFilterIcon() {
  return (
    <svg viewBox="0 0 24 24" width={18} height={18} aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 4h6v6H4V4zm10 0h6v6h-6V4zM4 14h6v6H4v-6zm10 0h6v6h-6v-6z"
      />
    </svg>
  );
}

type Props = {
  models: CatalogModel[];
  active: ModelKind | null;
  onChange: (kind: ModelKind | null) => void;
};

export default function ModelsFilterBar({ models, active, onChange }: Props) {
  const counts = kindCounts(models);

  return (
    <div className="models-filter-bar" role="toolbar" aria-label="Filter models by type">
      <button
        type="button"
        className={`models-filter-chip${active === null ? " models-filter-chip--active" : ""}`}
        onClick={() => onChange(null)}
        aria-pressed={active === null}
      >
        <AllFilterIcon />
        <span>All</span>
        <span className="models-filter-chip__count">{models.length}</span>
      </button>
      {MODEL_KIND_ORDER.map((kind) => {
        const selected = active === kind;
        return (
          <button
            key={kind}
            type="button"
            className={`models-filter-chip${selected ? " models-filter-chip--active" : ""}`}
            onClick={() => onChange(selected ? null : kind)}
            aria-pressed={selected}
          >
            <FilterIcon kind={kind} />
            <span>{MODEL_KIND_LABELS[kind]}</span>
            <span className="models-filter-chip__count">{counts[kind]}</span>
          </button>
        );
      })}
    </div>
  );
}
