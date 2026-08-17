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
import StorageManagement from "./pages/admin/StorageManagement";
import MyActivity from "./pages/MyActivity";
import MediaLibrary from "./pages/MediaLibrary";
import UserManual from "./pages/user/UserManual";
import Roles from "./pages/admin/Roles";
import AgentsOverview from "./pages/admin/AgentsOverview";
import AgentStudio from "./pages/admin/AgentStudio";
import KnowledgeBases from "./pages/admin/KnowledgeBases";
import ToolRegistry from "./pages/admin/ToolRegistry";
import AgentEvaluations from "./pages/admin/AgentEvaluations";
import AgentApprovals from "./pages/admin/AgentApprovals";
import AgentActivity from "./pages/admin/AgentActivity";
import AgentUsageActivity from "./pages/admin/AgentUsageActivity";
import { isAdminPanelRole } from "./lib/rbac";
import { bootstrapSession, type SessionInfo } from "./api";

function useSessionGate() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    bootstrapSession()
      .then((value) => {
        if (active) setSession(value);
      })
      .catch(() => {
        if (active) setSession(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  return { session, loading };
}

function Private({ children }: { children: React.ReactNode }) {
  const { session, loading } = useSessionGate();
  if (loading) return <div className="app-loading">Loading…</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function PrivateAdmin({ children }: { children: React.ReactNode }) {
  const { session, loading } = useSessionGate();
  if (loading) return <div className="app-loading">Loading…</div>;
  if (!session) return <Navigate to="/login" replace />;
  if (!isAdminPanelRole(session.role)) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/admin"
        element={
          <PrivateAdmin>
            <AdminLayout />
          </PrivateAdmin>
        }
      >
        <Route index element={<AdminDashboard />} />
        <Route path="chat" element={<ChatPanel />} />
        <Route path="media" element={<MediaLibrary />} />
        <Route path="manual" element={<UserManual />} />
        <Route path="authentication" element={<Authentication />} />
        <Route path="smtp" element={<SmtpServer />} />
        <Route path="connections" element={<Connections />} />
        <Route path="connections/:connId/activity" element={<ConnectionActivity />} />
        <Route path="groups" element={<Groups />} />
        <Route path="groups/:groupId/activity" element={<GroupActivity />} />
        <Route path="models" element={<Models />} />
        <Route path="api-keys" element={<AdminApiKeys />} />
        <Route path="api-keys/:keyId/activity" element={<ApiKeyActivity />} />
        <Route path="api-keys/:keyId/logs" element={<ApiKeyLogs />} />
        <Route path="plans" element={<Plans />} />
        <Route path="roles" element={<Roles />} />
        <Route path="users" element={<Users />} />
        <Route path="deleted-users" element={<DeletedUsers />} />
        <Route path="users/:userId/activity" element={<UserActivity />} />
        <Route path="users/:userId/media" element={<AdminUserMedia />} />
        <Route path="my-activity" element={<MyActivity />} />
        <Route path="storage-management" element={<StorageManagement />} />
        <Route path="retention-policy" element={<RetentionPolicy />} />
        <Route path="storage" element={<Navigate to="/admin/storage-management" replace />} />
        <Route path="reports" element={<Reports />} />
        <Route path="logs" element={<ApiLogs />} />
        <Route path="operations" element={<Operations />} />
        <Route path="debug" element={<Operations />} />
        <Route path="database" element={<DatabaseMonitor />} />
        <Route path="agents" element={<AgentsOverview />} />
        <Route path="agents/studio" element={<AgentStudio />} />
        <Route path="agents/:agentId/activity" element={<AgentUsageActivity />} />
        <Route path="knowledge" element={<KnowledgeBases />} />
        <Route path="agent-tools" element={<ToolRegistry />} />
        <Route path="agent-evaluations" element={<AgentEvaluations />} />
        <Route path="agent-approvals" element={<AgentApprovals />} />
        <Route path="agent-activity" element={<AgentActivity />} />
        <Route path="docs" element={<Docs />} />
      </Route>
      <Route
        path="/app"
        element={
          <Private>
            <UserLayout />
          </Private>
        }
      >
        <Route index element={<Navigate to="chat" replace />} />
        <Route path="chat" element={<ChatPanel />} />
        <Route path="media" element={<MediaLibrary />} />
        <Route path="my-activity" element={<MyActivity />} />
        <Route path="manual" element={<UserManual />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
