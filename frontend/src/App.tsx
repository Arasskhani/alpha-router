import { Navigate, Route, Routes } from "react-router-dom";
import { Suspense, lazy, useEffect, useState } from "react";
import RouteErrorBoundary from "./components/RouteErrorBoundary";
import Login from "./pages/Login";
import AdminLayout from "./pages/admin/AdminLayout";
import UserLayout from "./pages/user/UserLayout";
import { isAdminPanelRole } from "./lib/rbac";
import { bootstrapSession, type SessionInfo } from "./api";

// Every page is its own chunk (Phase 4.6): the shell, the login page and the
// layouts load first; a route downloads only when it is visited.
const AdminDashboard = lazy(() => import("./pages/admin/Dashboard"));
const Connections = lazy(() => import("./pages/admin/Connections"));
const ConnectionActivity = lazy(() => import("./pages/admin/ConnectionActivity"));
const Models = lazy(() => import("./pages/admin/Models"));
const AdminApiKeys = lazy(() => import("./pages/admin/ApiKeys"));
const ApiKeyActivity = lazy(() => import("./pages/admin/ApiKeyActivity"));
const ApiKeyLogs = lazy(() => import("./pages/admin/ApiKeyLogs"));
const Plans = lazy(() => import("./pages/admin/Plans"));
const Users = lazy(() => import("./pages/admin/Users"));
const DeletedUsers = lazy(() => import("./pages/admin/DeletedUsers"));
const UserActivity = lazy(() => import("./pages/admin/UserActivity"));
const AdminUserMedia = lazy(() => import("./pages/admin/AdminUserMedia"));
const Reports = lazy(() => import("./pages/admin/Reports"));
const ApiLogs = lazy(() => import("./pages/admin/ApiLogs"));
const AdminLogs = lazy(() => import("./pages/admin/AdminLogs"));
const Operations = lazy(() => import("./pages/admin/Operations"));
const DatabaseMonitor = lazy(() => import("./pages/admin/DatabaseMonitor"));
const ChatPanel = lazy(() => import("./components/ChatPanel"));
const Authentication = lazy(() => import("./pages/admin/Authentication"));
const SmtpServer = lazy(() => import("./pages/admin/SmtpServer"));
const Groups = lazy(() => import("./pages/admin/Groups"));
const GroupActivity = lazy(() => import("./pages/admin/GroupActivity"));
const Docs = lazy(() => import("./pages/admin/Docs"));
const RetentionPolicy = lazy(() => import("./pages/admin/RetentionPolicy"));
const MemoryAdmin = lazy(() => import("./pages/admin/Memory"));
const StorageManagement = lazy(() => import("./pages/admin/StorageManagement"));
const MyActivity = lazy(() => import("./pages/MyActivity"));
const MediaLibrary = lazy(() => import("./pages/MediaLibrary"));
const UserManual = lazy(() => import("./pages/user/UserManual"));
const Roles = lazy(() => import("./pages/admin/Roles"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const ProjectWorkspacePage = lazy(() => import("./pages/ProjectWorkspace"));
const ProjectInviteClaimPage = lazy(() => import("./pages/ProjectInviteClaim"));
const ProjectActivity = lazy(() => import("./pages/ProjectActivity"));
const AdminProjectActivityRedirect = lazy(() => import("./pages/ProjectActivity").then((m) => ({ default: m.AdminProjectActivityRedirect })));
const ProjectUsage = lazy(() => import("./pages/admin/ProjectUsage"));
const AgentsOverview = lazy(() => import("./pages/admin/AgentsOverview"));
const AgentStudio = lazy(() => import("./pages/admin/AgentStudio"));
const KnowledgeBases = lazy(() => import("./pages/admin/KnowledgeBases"));
const ToolRegistry = lazy(() => import("./pages/admin/ToolRegistry"));
const AgentEvaluations = lazy(() => import("./pages/admin/AgentEvaluations"));
const AgentApprovals = lazy(() => import("./pages/admin/AgentApprovals"));
const AgentActivity = lazy(() => import("./pages/admin/AgentActivity"));
const AgentUsageActivity = lazy(() => import("./pages/admin/AgentUsageActivity"));
const SecuritySettings = lazy(() => import("./pages/admin/SecuritySettings"));


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
    <RouteErrorBoundary title="Alpharouter could not start">
      <Suspense fallback={<div className="app-loading">Loading…</div>}>
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
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId/activity" element={<AdminProjectActivityRedirect />} />
        <Route path="projects/:projectId" element={<ProjectWorkspacePage />} />
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
        <Route path="memory" element={<MemoryAdmin />} />
        <Route path="storage" element={<Navigate to="/admin/storage-management" replace />} />
        <Route path="reports" element={<Reports />} />
        <Route path="project-usage" element={<ProjectUsage />} />
        <Route path="logs" element={<ApiLogs />} />
        <Route path="admin-logs" element={<AdminLogs />} />
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
        <Route path="security-settings" element={<SecuritySettings />} />
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
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/invite" element={<ProjectInviteClaimPage />} />
        <Route path="projects/:projectId/activity" element={<ProjectActivity />} />
        <Route path="projects/:projectId" element={<ProjectWorkspacePage />} />
        <Route path="media" element={<MediaLibrary />} />
        <Route path="my-activity" element={<MyActivity />} />
        <Route path="manual" element={<UserManual />} />
      </Route>
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    </RouteErrorBoundary>
  );
}
