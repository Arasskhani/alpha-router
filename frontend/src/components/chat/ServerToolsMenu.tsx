import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { DEFAULT_CHAT_TOOLS, type ChatToolsState } from "../../lib/chatTools";
import {
  DEFAULT_CUSTOM_ASPECT_RATIO,
  IMAGE_ASPECT_PRESETS,
  normalizeCustomAspectRatio,
  normalizeImageAspectPreset,
  SUPPORTED_ASPECT_RATIOS,
  type ImageAspectPresetId,
} from "../../lib/imageSize";

type Props = {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  tools: ChatToolsState;
  privateMode: boolean;
  onChange: (next: ChatToolsState) => void;
  onPrivateModeChange: (next: boolean) => void;
  onClose: () => void;
};

function Toggle({
  on,
  onToggle,
  label,
  disabled = false,
  disabledTitle,
}: {
  on: boolean;
  onToggle: () => void;
  label: string;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  return (
    <button
      type="button"
      className={`alpha-router-toggle${on ? " on" : ""}`}
      disabled={disabled}
      title={disabled ? disabledTitle : undefined}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      aria-label={label}
      aria-pressed={on}
    >
      <span className="alpha-router-toggle-knob" />
    </button>
  );
}

function ToolRow({
  icon,
  title,
  description,
  on,
  onToggle,
  disabled = false,
  disabledTitle,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  on: boolean;
  onToggle: () => void;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  return (
    <div
      className={`alpha-router-server-tool${disabled ? " is-disabled" : ""}`}
      onMouseDown={(e) => e.stopPropagation()}
      title={disabled ? disabledTitle : undefined}
    >
      <span className="alpha-router-server-tool__icon" aria-hidden>
        {icon}
      </span>
      <div className="alpha-router-server-tool__text">
        <strong>{title}</strong>
        <span className="alpha-router-server-tool__desc">{description}</span>
      </div>
      <Toggle
        on={on}
        onToggle={onToggle}
        label={`Toggle ${title}`}
        disabled={disabled}
        disabledTitle={disabledTitle}
      />
    </div>
  );
}

const MENU_WIDTH = 300;

export default function ServerToolsMenu({
  open,
  anchorRef,
  tools,
  privateMode,
  onChange,
  onPrivateModeChange,
  onClose,
}: Props) {
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);
  const [customAspectDraft, setCustomAspectDraft] = useState(tools.imageCustomAspectRatio);

  useEffect(() => {
    if (open) setCustomAspectDraft(tools.imageCustomAspectRatio);
  }, [open, tools.imageCustomAspectRatio]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = () => {
      const el = anchorRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const width = Math.min(MENU_WIDTH, window.innerWidth - 16);
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
      const bottom = window.innerHeight - rect.top + 8;
      setPos({ left, bottom });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchorRef]);

  if (!open || !pos) return null;

  function patch(partial: Partial<ChatToolsState>) {
    onChange({ ...tools, ...partial });
  }

  const activePreset = normalizeImageAspectPreset(tools.imageAspectRatio);
  const customAspectValid = normalizeCustomAspectRatio(customAspectDraft);

  function commitCustomAspect(raw = customAspectDraft) {
    const normalized = normalizeCustomAspectRatio(raw);
    if (normalized) {
      patch({ imageAspectRatio: "custom", imageCustomAspectRatio: normalized });
      setCustomAspectDraft(normalized);
    } else if (raw.trim()) {
      setCustomAspectDraft(tools.imageCustomAspectRatio);
    }
  }

  function selectPreset(presetId: ImageAspectPresetId) {
    patch({ imageAspectRatio: presetId });
  }

  function selectCustom() {
    const normalized =
      normalizeCustomAspectRatio(customAspectDraft) ?? tools.imageCustomAspectRatio;
    patch({
      imageAspectRatio: "custom",
      imageCustomAspectRatio: normalizeCustomAspectRatio(normalized) ?? DEFAULT_CUSTOM_ASPECT_RATIO,
    });
  }

  return createPortal(
    <div
      className="alpha-router-server-tools-menu"
      role="menu"
      aria-label="Chat Tools"
      style={{ left: pos.left, bottom: pos.bottom, width: Math.min(MENU_WIDTH, window.innerWidth - 16) }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <header className="alpha-router-server-tools-menu__head">Chat Tools</header>

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="9" />
            <path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20" />
          </svg>
        }
        title="Web Search"
        description="Fresh web results"
        on={tools.webSearch}
        onToggle={() => patch({ webSearch: !tools.webSearch })}
      />

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
        }
        title="Web Fetch"
        description="Read links in your message"
        on={tools.webFetch}
        onToggle={() => patch({ webFetch: !tools.webFetch })}
      />

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <circle cx="8.5" cy="11" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
        }
        title="Image Generation"
        description="Create or edit images from text"
        on={tools.imageGeneration}
        onToggle={() => patch({ imageGeneration: !tools.imageGeneration })}
      />

      {tools.imageGeneration ? (
        <div className="alpha-router-image-aspect-picker" onMouseDown={(e) => e.stopPropagation()}>
          <span className="alpha-router-image-aspect-picker__label">Aspect ratio</span>
          <div className="alpha-router-image-aspect-picker__options" role="group" aria-label="Image aspect ratio">
            {IMAGE_ASPECT_PRESETS.map((preset) => {
              const active = activePreset === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  className={`alpha-router-image-aspect-picker__chip${active ? " active" : ""}`}
                  aria-pressed={active}
                  title={`${preset.label} (${preset.aspectRatio})`}
                  onClick={() => selectPreset(preset.id as ImageAspectPresetId)}
                >
                  {preset.shortLabel}
                </button>
              );
            })}
            <button
              type="button"
              className={`alpha-router-image-aspect-picker__chip${activePreset === "custom" ? " active" : ""}`}
              aria-pressed={activePreset === "custom"}
              title="Custom aspect ratio (W:H)"
              onClick={selectCustom}
            >
              Custom
            </button>
          </div>
          {activePreset === "custom" ? (
            <div className="alpha-router-image-aspect-picker__custom">
              <input
                type="text"
                className="alpha-router-image-aspect-picker__custom-input"
                value={customAspectDraft}
                placeholder={DEFAULT_CUSTOM_ASPECT_RATIO}
                aria-label="Custom aspect ratio (width:height)"
                onChange={(e) => {
                  const v = e.target.value;
                  setCustomAspectDraft(v);
                  const normalized = normalizeCustomAspectRatio(v);
                  if (normalized) {
                    patch({ imageAspectRatio: "custom", imageCustomAspectRatio: normalized });
                  }
                }}
                onBlur={() => commitCustomAspect()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitCustomAspect();
                  }
                }}
              />
              <span className="alpha-router-image-aspect-picker__custom-hint">
                {customAspectValid
                  ? `${customAspectValid} (supported: ${SUPPORTED_ASPECT_RATIOS.join(", ")})`
                  : `W:H e.g. 21:9 or 16:9`}
              </span>
            </div>
          ) : null}
          <span className="alpha-router-image-aspect-picker__hint">
            Text-to-image uses this aspect ratio. With a source attachment (image-to-image), output size matches the
            source image. Override in prompt: <code>--ar 16:9</code>
          </span>
        </div>
      ) : null}

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </svg>
        }
        title="Code Interpreter"
        description="Run Python on data & math"
        on={tools.codeInterpreter}
        onToggle={() => patch({ codeInterpreter: !tools.codeInterpreter })}
      />

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            <circle cx="12" cy="12" r="2" />
          </svg>
        }
        title="Connectors"
        description="Use your connected apps (Gmail, Drive…)"
        on={tools.connectors}
        onToggle={() => patch({ connectors: !tools.connectors })}
      />

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5z" />
            <circle cx="12" cy="14" r="1.5" />
          </svg>
        }
        title="Private Mode"
        description={
          privateMode
            ? "Permanent for this chat — start a new chat for normal mode"
            : "Store this chat and its media on this device only"
        }
        on={privateMode}
        onToggle={() => onPrivateModeChange(!privateMode)}
        disabled={privateMode}
        disabledTitle="Private Mode cannot be turned off for this chat. Start a new chat to use normal mode."
      />

      <footer className="alpha-router-server-tools-menu__foot">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            onChange({ ...DEFAULT_CHAT_TOOLS });
          }}
        >
          Reset defaults
        </button>
      </footer>
    </div>,
    document.body,
  );
}
