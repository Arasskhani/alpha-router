import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import MediaLibrary from "../MediaLibrary";
export default function AdminUserMedia() {
    const { userId } = useParams();
    const id = Number(userId);
    if (!Number.isFinite(id)) {
        return _jsx("p", { className: "alert alert-error", children: "Invalid user id." });
    }
    return (_jsx(MediaLibrary, { adminUserId: id, backLink: { to: "/admin/users", label: "← Users" } }));
}
