import { useMemo } from "react";
import { getCachedSession } from "../api";
import ActivityView from "../components/activity/ActivityView";
import { getSessionUser } from "../lib/session";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
import { userHomePath } from "../lib/userPanelNav";

const HOME_LABELS: Record<string, string> = { "/app/chat": "Chat", "/app/projects": "Projects", "/app/media": "Media" };

export default function MyActivity() {
  const user = getSessionUser();
  const backLink = useMemo(() => {
    if (user?.role === "admin") return { to: "/admin/chat", label: "← Chat" };
    // Chat, or the first section Feature Access left open for this account.
    const home = userHomePath(getCachedSession());
    return { to: home, label: `← ${HOME_LABELS[home] ?? "Back"}` };
  }, [user?.role]);

  return <ActivityView scope="mine" title={MY_USAGE_AND_ACTIVITY_LABEL} backLink={backLink} />;
}
