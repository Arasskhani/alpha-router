import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getCachedSession, onSessionReady } from "../api";
import { sectionEnabled, userHomePath, type WebSection } from "../lib/userPanelNav";

const TITLES: Record<WebSection, string> = { chat: "Chat", projects: "Projects" };

/**
 * A web section Feature Access can close (Chat, Projects): its page when the
 * account may open it, and a plain explanation instead when it may not - not
 * a page that loads and then fails on every request.
 */
export default function SectionGate({ section, children }: { section: WebSection; children: React.ReactNode }) {
  const [session, setSession] = useState(getCachedSession);
  useEffect(() => onSessionReady(setSession), []);

  if (sectionEnabled(session, section)) return <>{children}</>;

  const home = userHomePath(session);
  const title = TITLES[section];
  return (
    <section className="section-not-enabled" aria-labelledby="section-not-enabled-title">
      <h1 id="section-not-enabled-title">{title} isn't enabled for you</h1>
      <p>
        Your administrator has turned {title} off for your account. Ask them if you need it.
        {section === "chat" ? " Your project chats still work in Projects." : null}
      </p>
      {home !== `/app/${section}` ? (
        <Link className="btn" to={home}>
          Go to {home === "/app/projects" ? "Projects" : home === "/app/chat" ? "Chat" : "Media"}
        </Link>
      ) : null}
    </section>
  );
}
