import { useEffect, useState } from "react";
import { bootstrapSession, type SessionInfo } from "../api";

/** The current session, once the server has said whether there is one. */
export function useSessionGate(): { session: SessionInfo | null; loading: boolean } {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    bootstrapSession()
      .then((value) => {
        if (active) setSession(value);
      })
      .catch(() => {
        if (active) setSession(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  return { session, loading };
}
