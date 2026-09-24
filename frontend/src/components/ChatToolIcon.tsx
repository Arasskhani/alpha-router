/**
 * The glyph for one chat tool, by the icon name in the server-side registry.
 *
 * Two places draw these now — the composer's tools menu and the admin page
 * that grants them — and they have to be the same picture, or the operator is
 * granting something that looks like a different tool to the user. The
 * registry sends a name rather than markup, so this is where a name becomes a
 * drawing; an unregistered name gets the generic glyph instead of nothing.
 */
export default function ChatToolIcon({ name, size = 16 }: { name: string; size?: number }) {
  const common = {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    "aria-hidden": true,
  } as const;

  switch (name) {
    case "globe":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20" />
        </svg>
      );
    case "link":
      return (
        <svg {...common}>
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      );
    case "image":
      return (
        <svg {...common}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <circle cx="8.5" cy="11" r="1.5" />
          <path d="m21 15-5-5L5 21" />
        </svg>
      );
    case "video":
      return (
        <svg {...common}>
          <rect x="3" y="6" width="14" height="12" rx="2" />
          <path d="m17 10 4-2v8l-4-2z" />
        </svg>
      );
    case "speaker":
      return (
        <svg {...common}>
          <path d="M11 5 6 9H2v6h4l5 4V5z" />
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
        </svg>
      );
    case "microphone":
      return (
        <svg {...common}>
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v4" />
        </svg>
      );
    case "terminal":
      return (
        <svg {...common}>
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      );
    case "lock":
      return (
        <svg {...common}>
          <path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5z" />
          <circle cx="12" cy="14" r="1.5" />
        </svg>
      );
    case "puzzle":
      return (
        <svg {...common}>
          <path d="M4 7h4a2 2 0 1 1 4 0h4v4a2 2 0 1 1 0 4v4H4z" />
        </svg>
      );
    case "cursor":
      return (
        <svg {...common}>
          <path d="M5 3l14 7-6 2-2 6z" />
          <path d="m13 12 5 5" />
        </svg>
      );
    default:
      // A tool registered with an icon this client has not learned yet still
      // needs a row on the page.
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5" />
          <circle cx="12" cy="16" r="0.6" fill="currentColor" />
        </svg>
      );
  }
}
