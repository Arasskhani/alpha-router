import type { NavSection } from "./types";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";

/** Admin sidebar — grouped for scanability (option 2). */
export const adminNavSections: NavSection[] = [
  {
    title: "User panel",
    categoryKey: "overview",
    items: [
      { to: "/app/chat", label: "Chat", icon: "chat" },
      { to: "/app/projects", label: "Projects", icon: "projects" },
      { to: "/app/media", label: "Media", icon: "media" },
      { to: "/app/my-activity", label: MY_USAGE_AND_ACTIVITY_LABEL, icon: "activity" },
      { to: "/app/manual", label: "User Manual", icon: "manual" },
    ],
  },
  {
    title: "Overview",
    categoryKey: "overview",
    items: [
      { to: "/admin", label: "Dashboard", menuKey: "dashboard" },
      { to: "/admin/operations", label: "Operations", menuKey: "operations" },
      { to: "/admin/code-interpreter", label: "Code Interpreter", menuKey: "operations" },
      { to: "/admin/database", label: "Database", menuKey: "database" },
    ],
  },
  {
    title: "Models & API",
    categoryKey: "models_api",
    items: [
      { to: "/admin/connections", label: "Connections", menuKey: "connections" },
      { to: "/admin/models", label: "Models", menuKey: "models" },
      { to: "/admin/api-keys", label: "API Keys", menuKey: "api_keys" },
    ],
  },
  {
    title: "Agents & Knowledge (preview)",
    categoryKey: "agents_knowledge",
    items: [
      { to: "/admin/agents", label: "Overview", menuKey: "agents" },
      { to: "/admin/agents/studio", label: "Agent Studio", menuKey: "agents" },
      { to: "/admin/knowledge", label: "Knowledge Bases", menuKey: "agents" },
      { to: "/admin/agent-tools", label: "Tool Registry", menuKey: "agents" },
      { to: "/admin/agent-evaluations", label: "Evaluations", menuKey: "agents" },
      { to: "/admin/agent-approvals", label: "Approvals", menuKey: "agents" },
      { to: "/admin/agent-activity", label: "Audit", menuKey: "agents" },
    ],
  },
  {
    title: "People & access",
    categoryKey: "people_access",
    items: [
      { to: "/admin/roles", label: "Roles", menuKey: "roles" },
      { to: "/admin/users", label: "Users", menuKey: "users" },
      { to: "/admin/deleted-users", label: "Deleted Users", menuKey: "deleted_users" },
      { to: "/admin/groups", label: "Groups", menuKey: "groups" },
      { to: "/admin/plans", label: "Plans", menuKey: "plans" },
      { to: "/admin/authentication", label: "Authentication", menuKey: "authentication" },
    ],
  },
  {
    title: "Security",
    categoryKey: "security",
    items: [
      { to: "/admin/security-settings", label: "Security Settings", menuKey: "security_settings" },
    ],
  },
  {
    title: "Integrations",
    categoryKey: "integrations",
    items: [
      { to: "/admin/smtp", label: "SMTP Server", menuKey: "smtp" },
    ],
  },
  {
    title: "Data & reports",
    categoryKey: "data_reports",
    items: [
      { to: "/admin/storage-management", label: "Storage Management", menuKey: "storage" },
      { to: "/admin/retention-policy", label: "Retention Policy", menuKey: "storage" },
      { to: "/admin/memory", label: "Memory", menuKey: "storage" },
      { to: "/admin/reports", label: "Reports", menuKey: "reports" },
      { to: "/admin/project-usage", label: "Projects", menuKey: "reports" },
      { to: "/admin/logs", label: "API Logs", menuKey: "api_logs" },
      { to: "/admin/admin-logs", label: "Admin Logs", menuKey: "api_logs" },
    ],
  },
  {
    title: "Developer",
    categoryKey: "developer",
    muted: true,
    items: [
      { to: "/admin/docs", label: "Admin Guide", menuKey: "admin_guide" },
      { to: "/admin/manual", label: "User Manual", menuKey: "user_manual" },
    ],
  },
];
