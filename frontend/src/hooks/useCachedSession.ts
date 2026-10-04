import { useEffect, useState } from "react";

import { getCachedSession, onSessionReady, type SessionInfo } from "../api";

/**
 * The signed-in session, kept current: re-rendered each time the server
 * confirms it again (the user layout re-reads it on focus, and a refusal by
 * Feature Access re-reads it), so menus drawn from it follow a change.
 */
export function useCachedSession(): SessionInfo | null {
  const [session, setSession] = useState<SessionInfo | null>(getCachedSession);
  useEffect(() => onSessionReady(setSession), []);
  return session;
}
