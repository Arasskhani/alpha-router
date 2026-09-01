import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from "react";
import { citationDisplayMarker, fetchAgentCitation, openAgentCitationSource, } from "../../lib/agentChat";
export function AgentHandoffBanner({ handoff, busy, onAccept, onDecline, }) {
    const source = handoff.from_agent_name || "Current Agent";
    const target = handoff.to_agent_name || "another specialist";
    return (_jsxs("div", { className: "alpha-router-handoff", role: "alert", children: [_jsx("div", { className: "alpha-router-handoff__icon", "aria-hidden": true, children: _jsxs("svg", { viewBox: "0 0 24 24", width: "20", height: "20", fill: "none", stroke: "currentColor", strokeWidth: "1.8", children: [_jsx("path", { d: "M5 7h11", strokeLinecap: "round" }), _jsx("path", { d: "m13 4 3 3-3 3", strokeLinecap: "round", strokeLinejoin: "round" }), _jsx("path", { d: "M19 17H8", strokeLinecap: "round" }), _jsx("path", { d: "m11 14-3 3 3 3", strokeLinecap: "round", strokeLinejoin: "round" })] }) }), _jsxs("div", { className: "alpha-router-handoff__body", children: [_jsx("strong", { children: "Specialist handoff requested" }), _jsxs("p", { children: [source, " recommends continuing with ", _jsx("b", { children: target }), ".", handoff.reason ? ` ${handoff.reason}` : ""] })] }), _jsxs("div", { className: "alpha-router-handoff__actions", children: [_jsx("button", { type: "button", onClick: onDecline, disabled: busy, children: "Decline" }), _jsx("button", { type: "button", className: "alpha-router-handoff__accept", onClick: onAccept, disabled: busy, children: busy ? "Applying…" : "Accept handoff" })] })] }));
}
function citationLocation(citation) {
    const parts = [];
    if (citation.page_number != null)
        parts.push(`Page ${citation.page_number}`);
    if (citation.section)
        parts.push(citation.section);
    if (citation.authority)
        parts.push(citation.authority);
    return parts.join(" · ");
}
export function AgentCitationList({ runId, citations, onError, }) {
    const [listOpen, setListOpen] = useState(false);
    const [details, setDetails] = useState({});
    const [expanded, setExpanded] = useState({});
    const [busy, setBusy] = useState({});
    if (!runId || !citations?.length)
        return null;
    async function toggleDetails(citation) {
        const id = citation.citation_id;
        if (expanded[id]) {
            setExpanded((prev) => ({ ...prev, [id]: false }));
            return;
        }
        if (details[id]) {
            setExpanded((prev) => ({ ...prev, [id]: true }));
            return;
        }
        setBusy((prev) => ({ ...prev, [id]: "details" }));
        try {
            const detail = await fetchAgentCitation(runId, id);
            setDetails((prev) => ({ ...prev, [id]: detail }));
            setExpanded((prev) => ({ ...prev, [id]: true }));
        }
        catch (error) {
            onError?.(error);
        }
        finally {
            setBusy((prev) => {
                const next = { ...prev };
                delete next[id];
                return next;
            });
        }
    }
    async function openSource(citation, mode) {
        const id = citation.citation_id;
        setBusy((prev) => ({ ...prev, [id]: mode }));
        try {
            await openAgentCitationSource(runId, citation, mode);
        }
        catch (error) {
            onError?.(error);
        }
        finally {
            setBusy((prev) => {
                const next = { ...prev };
                delete next[id];
                return next;
            });
        }
    }
    const panelId = `agent-citations-${runId}`;
    return (_jsxs("aside", { className: `alpha-router-citations${listOpen ? " is-open" : ""}`, "aria-label": "Verified sources", children: [_jsxs("button", { type: "button", className: "alpha-router-citations__toggle", "aria-expanded": listOpen, "aria-controls": panelId, onClick: () => setListOpen((open) => !open), children: [_jsxs("span", { className: "alpha-router-citations__toggle-label", children: ["Verified sources", _jsx("span", { className: "alpha-router-citations__count", children: citations.length })] }), _jsx("span", { className: "alpha-router-citations__chevron", "aria-hidden": true, children: _jsx("svg", { viewBox: "0 0 16 16", width: "14", height: "14", fill: "none", children: _jsx("path", { d: "M4 6.25 8 10l4-3.75", stroke: "currentColor", strokeWidth: "1.6", strokeLinecap: "round", strokeLinejoin: "round" }) }) })] }), listOpen ? (_jsx("div", { id: panelId, className: "alpha-router-citations__list", role: "region", "aria-label": "Source list", children: citations.map((citation, index) => {
                    const id = citation.citation_id;
                    const detail = details[id] || citation;
                    const location = citationLocation(detail);
                    const canOpen = Boolean(detail.document_version_id);
                    return (_jsxs("article", { className: "alpha-router-citation", children: [_jsxs("div", { className: "alpha-router-citation__summary", children: [_jsx("span", { className: "alpha-router-citation__marker", dir: "ltr", children: citationDisplayMarker(citation, index) }), _jsxs("div", { className: "alpha-router-citation__meta", children: [_jsx("strong", { children: citation.title || citation.file_name || "Source document" }), _jsx("p", { children: location || citation.file_name || "Authorized knowledge source" })] }), _jsxs("div", { className: "alpha-router-citation__actions", children: [_jsx("button", { type: "button", onClick: () => void toggleDetails(citation), disabled: Boolean(busy[id]), children: busy[id] === "details"
                                                    ? "…"
                                                    : expanded[id]
                                                        ? "Hide"
                                                        : "Details" }), canOpen ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", onClick: () => void openSource(detail, "view"), disabled: Boolean(busy[id]), children: busy[id] === "view" ? "…" : "Open" }), _jsx("button", { type: "button", onClick: () => void openSource(detail, "download"), disabled: Boolean(busy[id]), children: busy[id] === "download" ? "…" : "Download" })] })) : null] })] }), expanded[id] ? (_jsxs("dl", { className: "alpha-router-citation__details", children: [detail.knowledge_base_name ? (_jsxs(_Fragment, { children: [_jsx("dt", { children: "Knowledge base" }), _jsx("dd", { children: detail.knowledge_base_name })] })) : null, detail.classification ? (_jsxs(_Fragment, { children: [_jsx("dt", { children: "Classification" }), _jsx("dd", { children: detail.classification })] })) : null, detail.file_name ? (_jsxs(_Fragment, { children: [_jsx("dt", { children: "File" }), _jsx("dd", { children: detail.file_name })] })) : null, detail.effective_from || detail.effective_to ? (_jsxs(_Fragment, { children: [_jsx("dt", { children: "Effective" }), _jsxs("dd", { children: [detail.effective_from || "Open", " \u2013", " ", detail.effective_to || "Current"] })] })) : null] })) : null] }, id));
                }) })) : null] }));
}
