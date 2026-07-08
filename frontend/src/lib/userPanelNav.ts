import type { NavItem } from "../nav/types";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "./usageActivityLabel";

/** User panel left sidebar (non-admin accounts). */
export const USER_SIDEBAR_NAV: NavItem[] = [
  { to: "/app/chat", label: "Chat" },
  { to: "/app/media", label: "Media" },
  { to: "/app/recommendations", label: "Recommendations" },
  { to: "/app/my-activity", label: MY_USAGE_AND_ACTIVITY_LABEL },
  { to: "/app/manual", label: "User Manual" },
];

/** Routes allowed for disabled (read-only) users besides direct URL blocking. */
export const USER_READ_ONLY_PATHS = [
  "/app/chat",
  "/app/recommendations",
  "/app/media",
  "/app/my-activity",
  "/app/manual",
] as const;

export function isUserReadOnlyPath(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  return USER_READ_ONLY_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}
