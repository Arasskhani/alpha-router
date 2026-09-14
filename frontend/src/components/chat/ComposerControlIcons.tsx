
/** Open-end wrench silhouette for the composer Tools control (no box). */
export function ComposerToolsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {/* Soft open-end wrench, ~45° — matches the attached tools mark */}
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

/** Human brain silhouette for the composer Agent control. */
export function ComposerAgentIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="19"
      height="19"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 6.4V19" />
      <path d="M12 7a3 3 0 0 0-3-3 2.5 2.5 0 0 0-2.4 1.8A2.7 2.7 0 0 0 4 8.4c0 .8.3 1.5.9 2A2.9 2.9 0 0 0 4 12.7c0 1 .5 1.9 1.3 2.4-.2.4-.3.8-.3 1.2A2.8 2.8 0 0 0 7.8 19c1.2 0 2.3-.7 2.9-1.8" />
      <path d="M12 7a3 3 0 0 1 3-3 2.5 2.5 0 0 1 2.4 1.8A2.7 2.7 0 0 1 20 8.4c0 .8-.3 1.5-.9 2A2.9 2.9 0 0 1 20 12.7c0 1-.5 1.9-1.3 2.4.2.4.3.8.3 1.2A2.8 2.8 0 0 1 16.2 19c-1.2 0-2.3-.7-2.9-1.8" />
    </svg>
  );
}

export function ComposerTranslateIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  );
}
