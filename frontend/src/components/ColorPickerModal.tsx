import Modal from "./Modal";

export const FOLDER_COLOR_PRESETS: Array<{ id: string; value: string | null; label: string }> = [
  { id: "default", value: null, label: "Default" },
  { id: "indigo", value: "#6366f1", label: "Indigo" },
  { id: "violet", value: "#8b5cf6", label: "Violet" },
  { id: "blue", value: "#3b82f6", label: "Blue" },
  { id: "cyan", value: "#06b6d4", label: "Cyan" },
  { id: "teal", value: "#14b8a6", label: "Teal" },
  { id: "green", value: "#22c55e", label: "Green" },
  { id: "amber", value: "#f59e0b", label: "Amber" },
  { id: "orange", value: "#f97316", label: "Orange" },
  { id: "red", value: "#ef4444", label: "Red" },
  { id: "pink", value: "#ec4899", label: "Pink" },
  { id: "slate", value: "#64748b", label: "Slate" },
];

type Props = {
  open: boolean;
  title?: string;
  value: string | null;
  onClose: () => void;
  onChange: (color: string | null) => void;
};

export default function ColorPickerModal({
  open,
  title = "Choose color",
  value,
  onClose,
  onChange,
}: Props) {
  const custom = value && !FOLDER_COLOR_PRESETS.some((p) => p.value === value) ? value : "#6366f1";

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="color-picker">
        <p className="color-picker-hint muted-text">Pick a color for this folder.</p>
        <div className="color-picker-grid" role="listbox" aria-label="Preset colors">
          {FOLDER_COLOR_PRESETS.map((preset) => {
            const selected =
              (preset.value === null && !value) || (preset.value !== null && preset.value === value);
            return (
              <button
                key={preset.id}
                type="button"
                role="option"
                aria-selected={selected}
                className={`color-picker-swatch${selected ? " is-selected" : ""}${preset.value === null ? " is-default" : ""}`}
                style={preset.value ? { background: preset.value } : undefined}
                title={preset.label}
                onClick={() => {
                  onChange(preset.value);
                  onClose();
                }}
              >
                {preset.value === null ? <span className="color-picker-swatch-label">Aa</span> : null}
              </button>
            );
          })}
        </div>
        <label className="color-picker-custom">
          <span>Custom</span>
          <input
            type="color"
            value={custom}
            onChange={(e) => onChange(e.target.value)}
            aria-label="Custom color"
          />
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              onChange(custom);
              onClose();
            }}
          >
            Apply custom
          </button>
        </label>
      </div>
    </Modal>
  );
}
