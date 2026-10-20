import type { GuardrailNotice } from "../../lib/guardrailNotices";

const TITLES: Record<GuardrailNotice["action"], string> = {
  redact: "Masked by your organisation's policy",
  route: "Answered as your organisation's policy requires",
  notice: "Your organisation's policy",
};

function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6l7-3z" fill="currentColor" fillOpacity=".15" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

/** What the organisation's Guardrails did to this turn, above the answer: one box per kind, in plain text. */
export default function GuardrailNotices({ notices }: { notices: GuardrailNotice[] }) {
  const kinds = [...new Set(notices.map((n) => n.action))];
  return (
    <>
      {kinds.map((kind) => (
        <div key={kind} className={`alpha-router-msg-guardrail alpha-router-msg-guardrail--${kind}`} role="note" aria-label="Guardrails">
          <ShieldIcon />
          <div>
            <strong className="alpha-router-msg-guardrail__title">{TITLES[kind]}</strong>
            {notices
              .filter((n) => n.action === kind)
              .map((n) => (
                <span key={n.message} className="alpha-router-msg-guardrail__line" dir="auto">
                  {n.message}
                </span>
              ))}
          </div>
        </div>
      ))}
    </>
  );
}

/** A turn the organisation's Guardrails refused, in place of an answer: the administrator's message, not a model's error. */
export function GuardrailRefusal({ message, heldBack }: { message: string; heldBack?: boolean }) {
  return (
    <div className="alpha-router-guardrail-refusal" role="alert">
      <ShieldIcon />
      <div>
        <strong className="alpha-router-guardrail-refusal__title">Not sent: your organisation's policy</strong>
        <p className="alpha-router-guardrail-refusal__message" dir="auto">{message}</p>
        <span className="alpha-router-guardrail-refusal__from">
          Message from your administrator{heldBack ? " · Your message is back in the box below to edit" : ""}
        </span>
      </div>
    </div>
  );
}
