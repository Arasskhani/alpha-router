import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
export default function AgentUsageActivity() {
    const { agentId } = useParams();
    return (_jsx(ActivityView, { scope: "agent", agentId: agentId, backLink: { to: "/admin/agents/studio", label: "Agent Studio" } }));
}
