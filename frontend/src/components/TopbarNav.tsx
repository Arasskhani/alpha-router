import { NavLink } from "react-router-dom";
import { getCachedSession } from "../api";
import type { SessionRbac } from "../lib/rbac";
import { getSessionUser } from "../lib/session";
import { topbarShortcutsForSession } from "../lib/userPanelNav";
import type { CachedTheme } from "../lib/themeCache";
import { NavIcon } from "./icons/navIcons";
import UserProfile from "./UserProfile";

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
            {item.icon ? <NavIcon name={item.icon} /> : null}
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <UserProfile theme={theme} onThemeChange={onThemeChange} />
    </div>
  );
}
