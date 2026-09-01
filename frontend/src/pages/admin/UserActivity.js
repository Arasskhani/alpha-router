import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
export default function UserActivity() {
    const { userId } = useParams();
    return (_jsx(ActivityView, { scope: "user", userId: Number(userId), backLink: { to: "/admin/users", label: "← Users" } }));
}
