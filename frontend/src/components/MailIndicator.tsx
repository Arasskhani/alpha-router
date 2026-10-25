import { IconMail, IconMailConnected } from "./icons/navIcons";
import { MAIL_OFF_LABEL, MAIL_ON_LABEL } from "../lib/mailChatSwitch";

type Props = {
  /** Mail is on for this chat. */
  on: boolean;
  onToggle: () => void;
};

/**
 * The envelope by the chat box: the mailbox is connected, and a press turns
 * mail off (or on again) for this chat. Shown only where a turn can use mail
 * (`mailIndicatorShown`); a bare icon like the Tools and Agent controls beside it.
 */
export default function MailIndicator({ on, onToggle }: Props) {
  const label = on ? MAIL_ON_LABEL : MAIL_OFF_LABEL;
  return (
    <button
      type="button"
      className={`alpha-router-composer-ctrl alpha-router-mail-ctrl${on ? "" : " is-off"}`}
      onClick={onToggle}
      aria-pressed={on}
      aria-label={label}
      title={label}
    >
      <span className="alpha-router-composer-ctrl__icon" aria-hidden>
        {on ? (
          <IconMailConnected />
        ) : (
          <>
            <IconMail />
            {/* A strike through the envelope, drawn like the icons' own 2px lines. */}
            <svg
              className="alpha-router-mail-ctrl__strike"
              width={16}
              height={16}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              aria-hidden
            >
              <path d="M3 3l18 18" />
            </svg>
          </>
        )}
      </span>
    </button>
  );
}
