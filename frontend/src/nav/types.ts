export type CategoryKey =
  | "overview"
  | "models_api"
  | "chat_experience"
  | "people_access"
  | "security"
  | "integrations"
  | "data_reports"
  | "agents_knowledge"
  | "developer";

export type MenuKey =

  | "dashboard"

  | "chat"

  | "media"

  | "connections"

  | "models"

  | "api_keys"

  | "roles"

  | "users"

  | "deleted_users"

  | "groups"

  | "plans"

  | "authentication"

  | "smtp"

  | "storage"

  | "reports"

  | "api_logs"

  | "operations"

  | "database"

  | "chat_tools"

  | "memory"

  | "agents"

  | "admin_guide"

  | "user_manual"

  | "security_settings";

export type NavIconKey = "chat" | "media" | "activity" | "manual" | "admin" | "folder" | "projects";

export type NavItem = {
  to: string;
  label: string;
  menuKey?: MenuKey;
  /** Optional leading outline icon (user panel / topbar). */
  icon?: NavIconKey;
};

export type NavSection = {

  title: string;

  /** Sidebar group key (legacy category grouping in Roles table). */

  categoryKey: CategoryKey;

  items: NavItem[];

  /** Softer styling for low-frequency items (e.g. Debug, Docs). */

  muted?: boolean;

};

export function isNavGrouped(nav: NavItem[] | NavSection[]): nav is NavSection[] {

  return nav.length > 0 && "items" in nav[0];

}
