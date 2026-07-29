import { NavLink } from "react-router-dom";
import { getCachedSession } from "../api";
import type { SessionRbac } from "../lib/rbac";
import { getSessionUser } from "../lib/session";
import { topbarShortcutsForSession } from "../lib/userPanelNav";
import UserProfile from "./UserProfile";
import type { CachedTheme } from "../lib/themeCache";

type Theme = CachedTheme;

type Props = {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
};

/** Top-bar actions: text shortcuts + faint profile menu (OpenRouter-style). */
export default function TopbarNav({ theme, onThemeChange }: Props) {
  const user = getSessionUser();
  if (!user) return null;

  const shortcuts = topbarShortcutsForSession(getCachedSession() as SessionRbac | null);

  return (
    <div className="topbar-nav">
      <nav className="topbar-shortcuts" aria-label="Quick links">
        {shortcuts.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `topbar-shortcut${isActive ? " topbar-shortcut--active" : ""}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <UserProfile theme={theme} onThemeChange={onThemeChange} />
    </div>
  );
}
