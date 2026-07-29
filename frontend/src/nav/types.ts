export type CategoryKey =
  | "overview"
  | "models_api"
  | "people_access"
  | "integrations"
  | "data_reports"
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

  | "admin_guide"

  | "user_manual";



export type NavItem = { to: string; label: string; menuKey?: MenuKey };



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



export function flattenNav(nav: NavItem[] | NavSection[]): NavItem[] {

  if (isNavGrouped(nav)) {

    return nav.flatMap((s) => s.items);

  }

  return nav;

}


