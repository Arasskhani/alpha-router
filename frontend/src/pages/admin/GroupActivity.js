import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
export default function GroupActivity() {
    const { groupId } = useParams();
    return (_jsx(ActivityView, { scope: "group", groupId: Number(groupId), backLink: { to: "/admin/groups", label: "← Groups" } }));
}
