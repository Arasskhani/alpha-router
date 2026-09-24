import { Navigate } from "react-router-dom";
import { useSessionGate } from "../hooks/useSessionGate";
import { homePathFor } from "../lib/homePath";

/**
 * "/": a signed-in user goes to their home page, anyone else to the sign-in
 * page. The installed app starts here, so it must not show the sign-in form to
 * someone who is already signed in.
 */
export default function HomeRedirect() {
  const { session, loading } = useSessionGate();
  if (loading) return <div className="app-loading">Loading…</div>;
  return <Navigate to={session ? homePathFor(session) : "/login"} replace />;
}
