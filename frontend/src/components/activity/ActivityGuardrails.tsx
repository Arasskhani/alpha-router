type Props = {
  blocked: number;
  flagged: number;
};

export default function ActivityGuardrails({ blocked, flagged }: Props) {
  return (
    <>
      <h2 className="activity-section-title">Guardrail Enforcement</h2>
      <div className="activity-guardrails-grid">
        <article className="activity-guard-card card">
          <div className="activity-guard-icon activity-guard-icon--blocked" aria-hidden>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3 4 7v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V7l-8-4z" />
              <path d="m9 12 6 6M15 12l-6 6" />
            </svg>
          </div>
          <div>
            <h3>Blocked Requests</h3>
            <p className="muted">Rejected before reaching the model</p>
          </div>
          <p className="activity-guard-value">{blocked}</p>
        </article>
        <article className="activity-guard-card card">
          <div className="activity-guard-icon activity-guard-icon--flagged" aria-hidden>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3 4 7v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V7l-8-4z" />
              <path d="m9 12 2.5 2.5L12 12l2.5-2.5" />
            </svg>
          </div>
          <div>
            <h3>Redacted &amp; Flagged</h3>
            <p className="muted">Content modified or logged for review</p>
          </div>
          <p className="activity-guard-value">{flagged}</p>
        </article>
      </div>
    </>
  );
}
