import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { NO_AGENT_SELECTION, type AgentCatalogItem } from "../../lib/agentChat";
import { ComposerAgentIcon } from "./ComposerControlIcons";

type Props = {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  agents: AgentCatalogItem[];
  /** Slug of the enabled Agent, or NO_AGENT_SELECTION when the chat runs without one. */
  selection: string;
  disabled?: boolean;
  disabledReason?: string;
  onToggle: (slug: string) => void;
  onClose: () => void;
};

const MENU_WIDTH = 300;

function AgentRow({
  agent,
  on,
  disabled,
  disabledReason,
  onToggle,
}: {
  agent: AgentCatalogItem;
  on: boolean;
  disabled: boolean;
  disabledReason?: string;
  onToggle: () => void;
}) {
  const description =
    (agent.description || "").trim()
    || (agent.routing?.description || "").trim()
    || (agent.category || "").trim()
    || "Answers from governed Knowledge with citations";
  return (
    <div
      className={`alpha-router-server-tool${disabled ? " is-disabled" : ""}`}
      onMouseDown={(e) => e.stopPropagation()}
      title={disabled ? disabledReason : undefined}
    >
      <span className="alpha-router-server-tool__icon" aria-hidden>
        <ComposerAgentIcon />
      </span>
      <div className="alpha-router-server-tool__text">
        <strong>{agent.name}</strong>
        <span className="alpha-router-server-tool__desc">{description}</span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={`Enable ${agent.name}`}
        className={`alpha-router-toggle${on ? " on" : ""}`}
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
      >
        <span className="alpha-router-toggle-knob" />
      </button>
    </div>
  );
}

export default function AgentMenu({
  open,
  anchorRef,
  agents,
  selection,
  disabled = false,
  disabledReason,
  onToggle,
  onClose,
}: Props) {
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);

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

  return createPortal(
    <div
      className="alpha-router-server-tools-menu alpha-router-agent-menu"
      role="menu"
      aria-label="Specialist Agents"
      style={{
        left: pos.left,
        bottom: pos.bottom,
        width: Math.min(MENU_WIDTH, window.innerWidth - 16),
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <header className="alpha-router-server-tools-menu__head">Specialist Agents</header>

      {agents.length ? (
        agents.map((agent) => (
          <AgentRow
            key={agent.id}
            agent={agent}
            on={selection === agent.slug}
            disabled={disabled}
            disabledReason={disabledReason}
            onToggle={() => onToggle(agent.slug)}
          />
        ))
      ) : (
        <div className="alpha-router-agent-menu__empty">
          No Agents are published for your account yet.
        </div>
      )}

      <footer className="alpha-router-server-tools-menu__foot alpha-router-agent-menu__foot">
        <span>
          One Agent at a time. An Agent answers from its Knowledge with citations, so chat Tools and
          extra models pause while it is on.
        </span>
        {selection !== NO_AGENT_SELECTION ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              onToggle(selection);
            }}
          >
            Turn off
          </button>
        ) : null}
      </footer>
    </div>,
    document.body,
  );
}
