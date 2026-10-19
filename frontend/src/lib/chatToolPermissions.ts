import { api } from "../api";

/**
 * Which chat tools this account may use.
 *
 * The server decides — `GET /api/chat/tools` returns one row per registered
 * tool with a verdict — and the composer only draws the ones that came back
 * permitted. Holding the answer in a module rather than threading it through
 * props matters for the second job it does: `normalizeChatTools` clamps saved
 * toggles against it, and that function is called from half a dozen places
 * that load a chat session, a project composer or a cached list.
 *
 * Why clamping is not optional: a chat's tool toggles are stored on the
 * server with the session (and a project chat's row is shared between the
 * people in the project), so a tool switched on last week — or by a
 * colleague — comes back on today. Without this, the client would keep asking
 * for a tool it is no longer allowed and collect a 403 on every turn.
 *
 * Unknown until the first load resolves, and that is deliberately permissive:
 * the menu shows what it always did while the answer is in flight, and the
 * server refuses anything that should not have been asked for. The client
 * hides tools to be pleasant; the server is what enforces.
 */
type ChatToolRow = {
  key: string;
  title: string;
  description: string;
  icon: string;
  permitted: boolean;
  /** False when the tool cannot run now (Web Search with no search service set up); absent means it can. */
  available?: boolean;
  unavailable_reason?: string;
};

let permitted: Set<string> | null = null;
/** Tools that are permitted but cannot run now, and why - the menu shows them off with the reason. */
let unavailable = new Map<string, string>();
let inFlight: Promise<Set<string>> | null = null;

/** True unless the server has told us this tool is off limits. */
export function chatToolAllowed(key: string): boolean {
  return permitted === null || permitted.has(key);
}

/** Why a permitted tool cannot run now, or "" when it can. */
export function chatToolUnavailableReason(key: string): string {
  return unavailable.get(key) ?? "";
}

/** Replace the cached answer. Exported for tests and for the 403 path. */
export function setPermittedChatTools(keys: Iterable<string> | null): void {
  permitted = keys === null ? null : new Set(keys);
}

/**
 * Load the verdicts, at most once per call site burst.
 *
 * Called when the app starts and again when the tools menu opens, so an
 * administrator's change reaches an open tab the next time the user goes
 * looking for a tool rather than only after a reload.
 */
export function loadChatToolPermissions(): Promise<Set<string>> {
  if (inFlight) return inFlight;
  inFlight = api<ChatToolRow[]>("/api/chat/tools")
    .then((rows) => {
      const allowed = new Set(rows.filter((row) => row.permitted).map((row) => row.key));
      permitted = allowed;
      unavailable = new Map(
        rows
          .filter((row) => row.available === false)
          .map((row) => [row.key, row.unavailable_reason || "Not available right now."] as [string, string]),
      );
      return allowed;
    })
    .catch(() => {
      // A failed load must not take tools away: leave the previous answer (or
      // "unknown") in place and let the server refuse what it will.
      return permitted ?? new Set<string>();
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/** Drop the cached answer — sign-out, and tests. */
export function resetChatToolPermissions(): void {
  permitted = null;
  unavailable = new Map();
  inFlight = null;
}
