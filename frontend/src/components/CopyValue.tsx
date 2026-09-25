import { useState } from "react";

import { copyTextToClipboard } from "../lib/clipboard";

/** A read-only value with a Copy button: IDs, URLs and policy values someone pastes elsewhere. */
export default function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyTextToClipboard(value)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }
  return (
    <label className="settings-field personal-api-key-field">
      <span className="settings-label">{label}</span>
      <div className="personal-api-key-field__row">
        <input readOnly value={value} className="settings-row__control mono personal-api-key-field__input" aria-label={label} />
        <button
          type="button"
          className="btn btn-sm btn-ghost personal-api-key-field__copy"
          onClick={() => void copy()}
          aria-label={`Copy ${label}`}
          title={`Copy ${label}`}
        >
          {copied ? "✓" : "Copy"}
        </button>
      </div>
    </label>
  );
}
