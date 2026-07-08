import { useMemo } from "react";
import { Link } from "react-router-dom";
import ActivityView from "../components/activity/ActivityView";
import { getSessionUser } from "../lib/session";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";

export default function MyActivity() {
  const user = getSessionUser();
  const backLink = useMemo(() => {
    const home = user?.role === "admin" ? "/admin/chat" : "/app/chat";
    return { to: home, label: "← Chat" };
  }, [user?.role]);

  return <ActivityView scope="mine" title={MY_USAGE_AND_ACTIVITY_LABEL} backLink={backLink} />;
}
