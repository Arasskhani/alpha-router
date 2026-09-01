import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { NO_AGENT_SELECTION } from "../../lib/agentChat";
import { ComposerAgentIcon } from "./ComposerControlIcons";
const MENU_WIDTH = 300;
function AgentRow({ agent, on, disabled, disabledReason, onToggle, }) {
    const description = (agent.description || "").trim()
        || (agent.routing?.description || "").trim()
        || (agent.category || "").trim()
        || "Answers from governed Knowledge with citations";
    return (_jsxs("div", { className: `alpha-router-server-tool${disabled ? " is-disabled" : ""}`, onMouseDown: (e) => e.stopPropagation(), title: disabled ? disabledReason : undefined, children: [_jsx("span", { className: "alpha-router-server-tool__icon", "aria-hidden": true, children: _jsx(ComposerAgentIcon, {}) }), _jsxs("div", { className: "alpha-router-server-tool__text", children: [_jsx("strong", { children: agent.name }), _jsx("span", { className: "alpha-router-server-tool__desc", children: description })] }), _jsx("button", { type: "button", role: "switch", "aria-checked": on, "aria-label": `Enable ${agent.name}`, className: `alpha-router-toggle${on ? " on" : ""}`, disabled: disabled, title: disabled ? disabledReason : undefined, onClick: (e) => {
                    e.stopPropagation();
                    onToggle();
                }, children: _jsx("span", { className: "alpha-router-toggle-knob" }) })] }));
}
export default function AgentMenu({ open, anchorRef, agents, selection, disabled = false, disabledReason, onToggle, onClose, }) {
    const [pos, setPos] = useState(null);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => {
            if (e.key === "Escape")
                onClose();
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
            if (!el)
                return;
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
    if (!open || !pos)
        return null;
    return createPortal(_jsxs("div", { className: "alpha-router-server-tools-menu alpha-router-agent-menu", role: "menu", "aria-label": "Specialist Agents", style: {
            left: pos.left,
            bottom: pos.bottom,
            width: Math.min(MENU_WIDTH, window.innerWidth - 16),
        }, onMouseDown: (e) => e.stopPropagation(), onClick: (e) => e.stopPropagation(), children: [_jsx("header", { className: "alpha-router-server-tools-menu__head", children: "Specialist Agents" }), agents.length ? (agents.map((agent) => (_jsx(AgentRow, { agent: agent, on: selection === agent.slug, disabled: disabled, disabledReason: disabledReason, onToggle: () => onToggle(agent.slug) }, agent.id)))) : (_jsx("div", { className: "alpha-router-agent-menu__empty", children: "No Agents are published for your account yet." })), _jsxs("footer", { className: "alpha-router-server-tools-menu__foot alpha-router-agent-menu__foot", children: [_jsx("span", { children: "One Agent at a time. An Agent answers from its Knowledge with citations, so chat Tools and extra models pause while it is on." }), selection !== NO_AGENT_SELECTION ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: (e) => {
                            e.stopPropagation();
                            onToggle(selection);
                        }, children: "Turn off" })) : null] })] }), document.body);
}
