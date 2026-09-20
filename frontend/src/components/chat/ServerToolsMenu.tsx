import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import {
  CHAT_TOOL_KEY_BY_FIELD,
  DEFAULT_CHAT_TOOLS,
  type ChatToolsState,
  videoDurationChoices,
} from "../../lib/chatTools";
import { chatToolAllowed, loadChatToolPermissions } from "../../lib/chatToolPermissions";
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
  allowPrivateMode?: boolean;
  videoCapabilities?: {
    supported_durations?: number[];
    supported_resolutions?: string[];
    supported_aspect_ratios?: string[];
  };
  speechCapabilities?: {
    supported_voices?: string[];
    supported_formats?: string[];
    supported_speeds?: [number, number] | number[];
    max_text_length?: number;
  };
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

/**
 * One tool in the menu.
 *
 * `toolKey` is the registry key this row asks the server for. A row whose
 * tool the account has not been given renders nothing at all: a disabled
 * toggle invites the question "why", and the answer — an administrator's
 * policy — is not something the chat window can usefully explain.
 */
function ToolRow({
  toolKey,
  icon,
  title,
  description,
  on,
  onToggle,
  disabled = false,
  disabledTitle,
}: {
  toolKey: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  on: boolean;
  onToggle: () => void;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  if (!chatToolAllowed(toolKey)) return null;
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
  allowPrivateMode = true,
  videoCapabilities,
  speechCapabilities,
}: Props) {
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);
  const [customAspectDraft, setCustomAspectDraft] = useState(tools.imageCustomAspectRatio);
  // Bumped when the permission answer arrives, because the answer itself lives
  // in a module (normalizeChatTools needs it from outside React) and changing
  // it does not re-render anything on its own.
  const [permissionsAt, setPermissionsAt] = useState(0);

  useEffect(() => {
    if (open) setCustomAspectDraft(tools.imageCustomAspectRatio);
  }, [open, tools.imageCustomAspectRatio]);

  useEffect(() => {
    // Re-read on every open: an administrator granting or revoking a tool
    // should reach a tab that has been sitting there all afternoon.
    if (!open) return;
    let cancelled = false;
    void loadChatToolPermissions().then(() => {
      if (!cancelled) setPermissionsAt(Date.now());
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

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
      data-permissions-at={permissionsAt}
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
        toolKey={CHAT_TOOL_KEY_BY_FIELD.webSearch}
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
        toolKey={CHAT_TOOL_KEY_BY_FIELD.webFetch}
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
        toolKey={CHAT_TOOL_KEY_BY_FIELD.imageGeneration}
        title="Image Generation"
        description="Create or edit images from text"
        on={tools.imageGeneration}
        onToggle={() =>
          patch({
            imageGeneration: !tools.imageGeneration,
            videoGeneration: !tools.imageGeneration ? false : tools.videoGeneration,
            speechGeneration: !tools.imageGeneration ? false : tools.speechGeneration,
          })
        }
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
            <rect x="3" y="6" width="14" height="12" rx="2" />
            <path d="m17 10 4-2v8l-4-2z" />
          </svg>
        }
        toolKey={CHAT_TOOL_KEY_BY_FIELD.videoGeneration}
        title="Video Generation"
        description="Create videos from text or an image"
        on={tools.videoGeneration}
        onToggle={() =>
          patch({
            videoGeneration: !tools.videoGeneration,
            imageGeneration: !tools.videoGeneration ? false : tools.imageGeneration,
            speechGeneration: !tools.videoGeneration ? false : tools.speechGeneration,
          })
        }
      />

      {tools.videoGeneration ? (
        <div className="alpha-router-image-aspect-picker" onMouseDown={(e) => e.stopPropagation()}>
          <span className="alpha-router-image-aspect-picker__label">Duration / resolution</span>
          <div className="alpha-router-image-aspect-picker__options" role="group" aria-label="Video duration">
            {videoDurationChoices(videoCapabilities?.supported_durations).map((sec) => {
              const active = tools.videoDuration === sec;
              return (
                <button
                  key={sec}
                  type="button"
                  className={`alpha-router-image-aspect-picker__chip${active ? " active" : ""}`}
                  aria-pressed={active}
                  onClick={() => patch({ videoDuration: sec })}
                >
                  {sec}s
                </button>
              );
            })}
          </div>
          <div className="alpha-router-image-aspect-picker__options" role="group" aria-label="Video resolution">
            {(videoCapabilities?.supported_resolutions?.length
              ? videoCapabilities.supported_resolutions
              : ["480p", "720p", "1080p"]
            ).map((res) => {
              const active = tools.videoResolution === res;
              return (
                <button
                  key={res}
                  type="button"
                  className={`alpha-router-image-aspect-picker__chip${active ? " active" : ""}`}
                  aria-pressed={active}
                  onClick={() => patch({ videoResolution: res as ChatToolsState["videoResolution"] })}
                >
                  {res}
                </button>
              );
            })}
          </div>
          <div className="alpha-router-image-aspect-picker__options" role="group" aria-label="Video aspect ratio">
            {(videoCapabilities?.supported_aspect_ratios?.length
              ? videoCapabilities.supported_aspect_ratios
              : ["16:9", "9:16", "1:1"]
            ).map((ar) => {
              const active = tools.videoAspectRatio === ar;
              return (
                <button
                  key={ar}
                  type="button"
                  className={`alpha-router-image-aspect-picker__chip${active ? " active" : ""}`}
                  aria-pressed={active}
                  onClick={() => patch({ videoAspectRatio: ar })}
                >
                  {ar}
                </button>
              );
            })}
          </div>
          <span className="alpha-router-image-aspect-picker__hint">
            Text-to-video uses these settings. Attach an image to animate it (image-to-video).
          </span>
          <label className="alpha-router-image-aspect-picker__audio">
            <input
              type="checkbox"
              checked={tools.videoGenerateAudio}
              onChange={(e) => patch({ videoGenerateAudio: e.target.checked })}
            />
            Generate audio when supported
          </label>
        </div>
      ) : null}

      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M11 5 6 9H2v6h4l5 4V5z" />
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
          </svg>
        }
        toolKey={CHAT_TOOL_KEY_BY_FIELD.speechGeneration}
        title="Text to Speech"
        description="Generate audio from text"
        on={tools.speechGeneration}
        onToggle={() =>
          patch({
            speechGeneration: !tools.speechGeneration,
            imageGeneration: !tools.speechGeneration ? false : tools.imageGeneration,
            videoGeneration: !tools.speechGeneration ? false : tools.videoGeneration,
          })
        }
      />

      {tools.speechGeneration ? (
        <div className="alpha-router-image-aspect-picker" onMouseDown={(e) => e.stopPropagation()}>
          <span className="alpha-router-image-aspect-picker__label">Voice</span>
          <div className="alpha-router-image-aspect-picker__options" role="group" aria-label="Speech voice">
            {(speechCapabilities?.supported_voices?.length
              ? speechCapabilities.supported_voices
              : []
            ).map((voice) => {
              const active = tools.speechVoice === voice;
              return (
                <button
                  key={voice}
                  type="button"
                  className={`alpha-router-image-aspect-picker__chip${active ? " active" : ""}`}
                  aria-pressed={active}
                  onClick={() => patch({ speechVoice: voice })}
                >
                  {voice}
                </button>
              );
            })}
          </div>
          <div className="alpha-router-image-aspect-picker__custom">
            <span className="alpha-router-image-aspect-picker__label">Speed</span>
            <input
              type="range"
              min={Number(speechCapabilities?.supported_speeds?.[0] ?? 0.25)}
              max={Number(speechCapabilities?.supported_speeds?.[1] ?? 4.0)}
              step={0.05}
              value={tools.speechSpeed}
              aria-label="Speech speed"
              onChange={(e) => patch({ speechSpeed: Number(e.target.value) })}
            />
            <span className="alpha-router-image-aspect-picker__custom-hint">{tools.speechSpeed.toFixed(2)}x</span>
          </div>
          <span className="alpha-router-image-aspect-picker__hint">
            Text-to-speech generates audio from your message text. Max{" "}
            {speechCapabilities?.max_text_length ?? 5000} characters.
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
        toolKey={CHAT_TOOL_KEY_BY_FIELD.codeInterpreter}
        title="Code Interpreter"
        description="Run Python on data & math"
        on={tools.codeInterpreter}
        onToggle={() => patch({ codeInterpreter: !tools.codeInterpreter })}
      />

      {allowPrivateMode ? (
      <ToolRow
        icon={
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5z" />
            <circle cx="12" cy="14" r="1.5" />
          </svg>
        }
        toolKey="private_mode"
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
      ) : null}

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
