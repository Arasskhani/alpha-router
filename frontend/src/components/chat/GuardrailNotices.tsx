/** What the organisation's Guardrails did to this turn, under the answer, as plain text. */
export default function GuardrailNotices({ notices }: { notices: string[] }) {
  return (
    <div className="alpha-router-msg-guardrail" role="note" aria-label="Guardrails">
      <span aria-hidden="true">🛡</span>
      <span>
        {notices.map((notice) => (
          <span key={notice} className="alpha-router-msg-guardrail__line">
            {notice}
          </span>
        ))}
      </span>
    </div>
  );
}
