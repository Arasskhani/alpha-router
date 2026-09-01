import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { formatApiError } from "../api";
import { claimInvitation } from "../lib/projectsApi";
export default function ProjectInviteClaimPage() {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    const token = params.get("token") ?? "";
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    const [projectId, setProjectId] = useState(null);
    useEffect(() => {
        if (!token) {
            setStatus("error");
            setError("Missing invitation token.");
            return;
        }
        let active = true;
        claimInvitation(token)
            .then((project) => {
            if (!active)
                return;
            setProjectId(project.id);
            setStatus("done");
        })
            .catch((err) => {
            if (!active)
                return;
            setError(formatApiError(err));
            setStatus("error");
        });
        return () => {
            active = false;
        };
    }, [token]);
    if (status === "loading") {
        return _jsx("div", { className: "admin-page", children: _jsx("div", { className: "loading-state", children: "Accepting invitation\u2026" }) });
    }
    if (status === "done" && projectId) {
        return (_jsxs("div", { className: "admin-page", children: [_jsx("div", { className: "flash flash-success", children: "You have joined the project." }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary", onClick: () => navigate(`/app/projects/${projectId}`), children: "Open project" }), _jsx(Link, { to: "/app/projects", className: "btn btn-ghost", children: "All projects" })] })] }));
    }
    return (_jsxs("div", { className: "admin-page", children: [_jsx("div", { className: "flash flash-error", children: error || "Invitation could not be accepted." }), _jsx("div", { className: "dialog-actions", children: _jsx(Link, { to: "/app/projects", className: "btn btn-ghost", children: "Back to projects" }) })] }));
}
