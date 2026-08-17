import { useState } from "react";
import {
  citationDisplayMarker,
  fetchAgentCitation,
  openAgentCitationSource,
  type AgentCitation,
  type AgentHandoff,
} from "../../lib/agentChat";

type AgentHandoffBannerProps = {
  handoff: AgentHandoff;
  busy?: boolean;
  onAccept: () => void;
  onDecline: () => void;
};

export function AgentHandoffBanner({
  handoff,
  busy,
  onAccept,
  onDecline,
}: AgentHandoffBannerProps) {
  const source = handoff.from_agent_name || "Current Agent";
  const target = handoff.to_agent_name || "another specialist";
  return (
    <div className="alpha-router-handoff" role="alert">
      <div className="alpha-router-handoff__icon" aria-hidden>
        <svg
          viewBox="0 0 24 24"
          width="20"
          height="20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
        >
          <path d="M5 7h11" strokeLinecap="round" />
          <path d="m13 4 3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M19 17H8" strokeLinecap="round" />
          <path d="m11 14-3 3 3 3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="alpha-router-handoff__body">
        <strong>Specialist handoff requested</strong>
        <p>
          {source} recommends continuing with <b>{target}</b>.
          {handoff.reason ? ` ${handoff.reason}` : ""}
        </p>
      </div>
      <div className="alpha-router-handoff__actions">
        <button type="button" onClick={onDecline} disabled={busy}>
          Decline
        </button>
        <button
          type="button"
          className="alpha-router-handoff__accept"
          onClick={onAccept}
          disabled={busy}
        >
          {busy ? "Applying…" : "Accept handoff"}
        </button>
      </div>
    </div>
  );
}

function citationLocation(citation: AgentCitation): string {
  const parts: string[] = [];
  if (citation.page_number != null) parts.push(`Page ${citation.page_number}`);
  if (citation.section) parts.push(citation.section);
  if (citation.authority) parts.push(citation.authority);
  return parts.join(" · ");
}

type AgentCitationListProps = {
  runId?: string;
  citations?: AgentCitation[];
  onError?: (error: unknown) => void;
};

export function AgentCitationList({
  runId,
  citations,
  onError,
}: AgentCitationListProps) {
  const [listOpen, setListOpen] = useState(false);
  const [details, setDetails] = useState<Record<string, AgentCitation>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<Record<string, string>>({});

  if (!runId || !citations?.length) return null;

  async function toggleDetails(citation: AgentCitation) {
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
      const detail = await fetchAgentCitation(runId!, id);
      setDetails((prev) => ({ ...prev, [id]: detail }));
      setExpanded((prev) => ({ ...prev, [id]: true }));
    } catch (error) {
      onError?.(error);
    } finally {
      setBusy((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  }

  async function openSource(
    citation: AgentCitation,
    mode: "view" | "download",
  ) {
    const id = citation.citation_id;
    setBusy((prev) => ({ ...prev, [id]: mode }));
    try {
      await openAgentCitationSource(runId!, citation, mode);
    } catch (error) {
      onError?.(error);
    } finally {
      setBusy((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  }

  const panelId = `agent-citations-${runId}`;

  return (
    <aside
      className={`alpha-router-citations${listOpen ? " is-open" : ""}`}
      aria-label="Verified sources"
    >
      <button
        type="button"
        className="alpha-router-citations__toggle"
        aria-expanded={listOpen}
        aria-controls={panelId}
        onClick={() => setListOpen((open) => !open)}
      >
        <span className="alpha-router-citations__toggle-label">
          Verified sources
          <span className="alpha-router-citations__count">{citations.length}</span>
        </span>
        <span className="alpha-router-citations__chevron" aria-hidden>
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none">
            <path
              d="M4 6.25 8 10l4-3.75"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>
      {listOpen ? (
        <div
          id={panelId}
          className="alpha-router-citations__list"
          role="region"
          aria-label="Source list"
        >
          {citations.map((citation, index) => {
            const id = citation.citation_id;
            const detail = details[id] || citation;
            const location = citationLocation(detail);
            const canOpen = Boolean(detail.document_version_id);
            return (
              <article key={id} className="alpha-router-citation">
                <div className="alpha-router-citation__summary">
                  <span className="alpha-router-citation__marker" dir="ltr">
                    {citationDisplayMarker(citation, index)}
                  </span>
                  <div className="alpha-router-citation__meta">
                    <strong>
                      {citation.title || citation.file_name || "Source document"}
                    </strong>
                    <p>
                      {location || citation.file_name || "Authorized knowledge source"}
                    </p>
                  </div>
                  <div className="alpha-router-citation__actions">
                    <button
                      type="button"
                      onClick={() => void toggleDetails(citation)}
                      disabled={Boolean(busy[id])}
                    >
                      {busy[id] === "details"
                        ? "…"
                        : expanded[id]
                          ? "Hide"
                          : "Details"}
                    </button>
                    {canOpen ? (
                      <>
                        <button
                          type="button"
                          onClick={() => void openSource(detail, "view")}
                          disabled={Boolean(busy[id])}
                        >
                          {busy[id] === "view" ? "…" : "Open"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void openSource(detail, "download")}
                          disabled={Boolean(busy[id])}
                        >
                          {busy[id] === "download" ? "…" : "Download"}
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
                {expanded[id] ? (
                  <dl className="alpha-router-citation__details">
                    {detail.knowledge_base_name ? (
                      <>
                        <dt>Knowledge base</dt>
                        <dd>{detail.knowledge_base_name}</dd>
                      </>
                    ) : null}
                    {detail.classification ? (
                      <>
                        <dt>Classification</dt>
                        <dd>{detail.classification}</dd>
                      </>
                    ) : null}
                    {detail.file_name ? (
                      <>
                        <dt>File</dt>
                        <dd>{detail.file_name}</dd>
                      </>
                    ) : null}
                    {detail.effective_from || detail.effective_to ? (
                      <>
                        <dt>Effective</dt>
                        <dd>
                          {detail.effective_from || "Open"} –{" "}
                          {detail.effective_to || "Current"}
                        </dd>
                      </>
                    ) : null}
                  </dl>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
    </aside>
  );
}
