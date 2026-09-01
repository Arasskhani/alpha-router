import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import Login from "./pages/Login";
import AdminLayout from "./pages/admin/AdminLayout";
import UserLayout from "./pages/user/UserLayout";
import AdminDashboard from "./pages/admin/Dashboard";
import Connections from "./pages/admin/Connections";
import ConnectionActivity from "./pages/admin/ConnectionActivity";
import Models from "./pages/admin/Models";
import AdminApiKeys from "./pages/admin/ApiKeys";
import ApiKeyActivity from "./pages/admin/ApiKeyActivity";
import ApiKeyLogs from "./pages/admin/ApiKeyLogs";
import Plans from "./pages/admin/Plans";
import Users from "./pages/admin/Users";
import DeletedUsers from "./pages/admin/DeletedUsers";
import UserActivity from "./pages/admin/UserActivity";
import AdminUserMedia from "./pages/admin/AdminUserMedia";
import Reports from "./pages/admin/Reports";
import ApiLogs from "./pages/admin/ApiLogs";
import Operations from "./pages/admin/Operations";
import DatabaseMonitor from "./pages/admin/DatabaseMonitor";
import ChatPanel from "./components/ChatPanel";
import Authentication from "./pages/admin/Authentication";
import SmtpServer from "./pages/admin/SmtpServer";
import Groups from "./pages/admin/Groups";
import GroupActivity from "./pages/admin/GroupActivity";
import Docs from "./pages/admin/Docs";
import RetentionPolicy from "./pages/admin/RetentionPolicy";
import MemoryAdmin from "./pages/admin/Memory";
import StorageManagement from "./pages/admin/StorageManagement";
import MyActivity from "./pages/MyActivity";
import MediaLibrary from "./pages/MediaLibrary";
import UserManual from "./pages/user/UserManual";
import Roles from "./pages/admin/Roles";
import ProjectsPage from "./pages/Projects";
import ProjectWorkspacePage from "./pages/ProjectWorkspace";
import ProjectInviteClaimPage from "./pages/ProjectInviteClaim";
import ProjectActivity, { AdminProjectActivityRedirect } from "./pages/ProjectActivity";
import ProjectUsage from "./pages/admin/ProjectUsage";
import AgentsOverview from "./pages/admin/AgentsOverview";
import AgentStudio from "./pages/admin/AgentStudio";
import KnowledgeBases from "./pages/admin/KnowledgeBases";
import ToolRegistry from "./pages/admin/ToolRegistry";
import AgentEvaluations from "./pages/admin/AgentEvaluations";
import AgentApprovals from "./pages/admin/AgentApprovals";
import AgentActivity from "./pages/admin/AgentActivity";
import AgentUsageActivity from "./pages/admin/AgentUsageActivity";
import SecuritySettings from "./pages/admin/SecuritySettings";
import { isAdminPanelRole } from "./lib/rbac";
import { bootstrapSession } from "./api";
function useSessionGate() {
    const [session, setSession] = useState(null);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        let active = true;
        bootstrapSession()
            .then((value) => {
            if (active)
                setSession(value);
        })
            .catch(() => {
            if (active)
                setSession(null);
        })
            .finally(() => {
            if (active)
                setLoading(false);
        });
        return () => {
            active = false;
        };
    }, []);
    return { session, loading };
}
function Private({ children }) {
    const { session, loading } = useSessionGate();
    if (loading)
        return _jsx("div", { className: "app-loading", children: "Loading\u2026" });
    if (!session)
        return _jsx(Navigate, { to: "/login", replace: true });
    return _jsx(_Fragment, { children: children });
}
function PrivateAdmin({ children }) {
    const { session, loading } = useSessionGate();
    if (loading)
        return _jsx("div", { className: "app-loading", children: "Loading\u2026" });
    if (!session)
        return _jsx(Navigate, { to: "/login", replace: true });
    if (!isAdminPanelRole(session.role))
        return _jsx(Navigate, { to: "/login", replace: true });
    return _jsx(_Fragment, { children: children });
}
export default function App() {
    return (_jsxs(Routes, { children: [_jsx(Route, { path: "/login", element: _jsx(Login, {}) }), _jsxs(Route, { path: "/admin", element: _jsx(PrivateAdmin, { children: _jsx(AdminLayout, {}) }), children: [_jsx(Route, { index: true, element: _jsx(AdminDashboard, {}) }), _jsx(Route, { path: "chat", element: _jsx(ChatPanel, {}) }), _jsx(Route, { path: "projects", element: _jsx(ProjectsPage, {}) }), _jsx(Route, { path: "projects/:projectId/activity", element: _jsx(AdminProjectActivityRedirect, {}) }), _jsx(Route, { path: "projects/:projectId", element: _jsx(ProjectWorkspacePage, {}) }), _jsx(Route, { path: "media", element: _jsx(MediaLibrary, {}) }), _jsx(Route, { path: "manual", element: _jsx(UserManual, {}) }), _jsx(Route, { path: "authentication", element: _jsx(Authentication, {}) }), _jsx(Route, { path: "smtp", element: _jsx(SmtpServer, {}) }), _jsx(Route, { path: "connections", element: _jsx(Connections, {}) }), _jsx(Route, { path: "connections/:connId/activity", element: _jsx(ConnectionActivity, {}) }), _jsx(Route, { path: "groups", element: _jsx(Groups, {}) }), _jsx(Route, { path: "groups/:groupId/activity", element: _jsx(GroupActivity, {}) }), _jsx(Route, { path: "models", element: _jsx(Models, {}) }), _jsx(Route, { path: "api-keys", element: _jsx(AdminApiKeys, {}) }), _jsx(Route, { path: "api-keys/:keyId/activity", element: _jsx(ApiKeyActivity, {}) }), _jsx(Route, { path: "api-keys/:keyId/logs", element: _jsx(ApiKeyLogs, {}) }), _jsx(Route, { path: "plans", element: _jsx(Plans, {}) }), _jsx(Route, { path: "roles", element: _jsx(Roles, {}) }), _jsx(Route, { path: "users", element: _jsx(Users, {}) }), _jsx(Route, { path: "deleted-users", element: _jsx(DeletedUsers, {}) }), _jsx(Route, { path: "users/:userId/activity", element: _jsx(UserActivity, {}) }), _jsx(Route, { path: "users/:userId/media", element: _jsx(AdminUserMedia, {}) }), _jsx(Route, { path: "my-activity", element: _jsx(MyActivity, {}) }), _jsx(Route, { path: "storage-management", element: _jsx(StorageManagement, {}) }), _jsx(Route, { path: "retention-policy", element: _jsx(RetentionPolicy, {}) }), _jsx(Route, { path: "memory", element: _jsx(MemoryAdmin, {}) }), _jsx(Route, { path: "storage", element: _jsx(Navigate, { to: "/admin/storage-management", replace: true }) }), _jsx(Route, { path: "reports", element: _jsx(Reports, {}) }), _jsx(Route, { path: "project-usage", element: _jsx(ProjectUsage, {}) }), _jsx(Route, { path: "logs", element: _jsx(ApiLogs, {}) }), _jsx(Route, { path: "operations", element: _jsx(Operations, {}) }), _jsx(Route, { path: "debug", element: _jsx(Operations, {}) }), _jsx(Route, { path: "database", element: _jsx(DatabaseMonitor, {}) }), _jsx(Route, { path: "agents", element: _jsx(AgentsOverview, {}) }), _jsx(Route, { path: "agents/studio", element: _jsx(AgentStudio, {}) }), _jsx(Route, { path: "agents/:agentId/activity", element: _jsx(AgentUsageActivity, {}) }), _jsx(Route, { path: "knowledge", element: _jsx(KnowledgeBases, {}) }), _jsx(Route, { path: "agent-tools", element: _jsx(ToolRegistry, {}) }), _jsx(Route, { path: "agent-evaluations", element: _jsx(AgentEvaluations, {}) }), _jsx(Route, { path: "agent-approvals", element: _jsx(AgentApprovals, {}) }), _jsx(Route, { path: "agent-activity", element: _jsx(AgentActivity, {}) }), _jsx(Route, { path: "security-settings", element: _jsx(SecuritySettings, {}) }), _jsx(Route, { path: "docs", element: _jsx(Docs, {}) })] }), _jsxs(Route, { path: "/app", element: _jsx(Private, { children: _jsx(UserLayout, {}) }), children: [_jsx(Route, { index: true, element: _jsx(Navigate, { to: "chat", replace: true }) }), _jsx(Route, { path: "chat", element: _jsx(ChatPanel, {}) }), _jsx(Route, { path: "projects", element: _jsx(ProjectsPage, {}) }), _jsx(Route, { path: "projects/invite", element: _jsx(ProjectInviteClaimPage, {}) }), _jsx(Route, { path: "projects/:projectId/activity", element: _jsx(ProjectActivity, {}) }), _jsx(Route, { path: "projects/:projectId", element: _jsx(ProjectWorkspacePage, {}) }), _jsx(Route, { path: "media", element: _jsx(MediaLibrary, {}) }), _jsx(Route, { path: "my-activity", element: _jsx(MyActivity, {}) }), _jsx(Route, { path: "manual", element: _jsx(UserManual, {}) })] }), _jsx(Route, { path: "*", element: _jsx(Navigate, { to: "/login", replace: true }) })] }));
}
