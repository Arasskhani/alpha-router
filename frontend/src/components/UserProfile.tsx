import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { clearStoredImageGenerationForCurrentUser } from "../lib/chatStorage";
import { formatSessionDuration, getMyActivityPath, getSessionUser, logout } from "../lib/session";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
import type { CachedTheme } from "../lib/themeCache";
import SettingsModal from "./SettingsModal";
import ThemePicker from "./ThemePicker";

type UserBudget = {
  monthly_budget_usd: number;
  used_usd: number;
  remaining_usd: number | null;
};

function formatBudgetUsd(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function formatBudgetLine(budget: UserBudget | null, loading: boolean): string {
  if (loading) return "…";
  if (!budget) return "—";
  if ((budget.monthly_budget_usd ?? 0) <= 0) return "No Plan";
  const used = formatBudgetUsd(budget.used_usd ?? 0);
  const total = formatBudgetUsd(budget.monthly_budget_usd ?? 0);
  return `${used}/${total} $`;
}

type Props = {
  theme: CachedTheme;
  onThemeChange: (theme: CachedTheme) => void;
};

function IconGear() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

/** Three descending bars — usage / activity mark. */
function IconUsageActivity() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M6 20V8" />
      <path d="M12 20v-8" />
      <path d="M18 20v-4" />
    </svg>
  );
}

export default function UserProfile({ theme, onThemeChange }: Props) {
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [duration, setDuration] = useState("");
  const [budget, setBudget] = useState<UserBudget | null>(null);
  const [budgetLoading, setBudgetLoading] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const user = getSessionUser();

  useEffect(() => {
    if (!user) return;
    const tick = () => setDuration(formatSessionDuration(user.loginAt));
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, [user?.loginAt]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setBudgetLoading(true);
    api<UserBudget>("/api/user/budget")
      .then(setBudget)
      .catch(() => setBudget(null))
      .finally(() => setBudgetLoading(false));
  }, [open]);

  if (!user) return null;

  // Single letter matches the faint reference topbar avatar style.
  const initials = (user.username.trim().charAt(0) || "?").toUpperCase();

  return (
    <div className="user-profile" ref={wrapRef}>
      <button
        type="button"
        className="user-profile-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <span className="user-avatar">{initials}</span>
        <span className="user-profile-name">{user.username}</span>
        <span className="user-profile-chevron" aria-hidden>▾</span>
      </button>

      {open && (
        <div className="user-profile-menu" role="menu">
          <div className="user-profile-menu-head">
            <span className="user-avatar user-avatar-lg">{initials}</span>
            <div>
              <div className="user-profile-menu-name">{user.username}</div>
              <div className="user-profile-menu-role">{user.role === "admin" ? "Administrator" : "User"}</div>
            </div>
          </div>
          <div className="user-profile-menu-meta">
            <span className="user-profile-meta-label">Signed in for</span>
            <span className="user-profile-meta-value">{duration || "—"}</span>
          </div>
          <div className="user-profile-menu-meta">
            <span className="user-profile-meta-label">Budget</span>
            <span className="user-profile-meta-value">{formatBudgetLine(budget, budgetLoading)}</span>
          </div>
          <div className="user-profile-menu-divider" />
          <Link
            to={getMyActivityPath(user.role)}
            className="user-profile-menu-item"
            role="menuitem"
            onClick={() => setOpen(false)}
          >
            <span className="user-profile-menu-icon"><IconUsageActivity /></span>
            <span>{MY_USAGE_AND_ACTIVITY_LABEL}</span>
          </Link>
          <button
            type="button"
            className="user-profile-menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              setSettingsOpen(true);
            }}
          >
            <span className="user-profile-menu-icon"><IconGear /></span>
            <span>Settings</span>
          </button>
          <button
            type="button"
            className="user-profile-menu-item user-profile-menu-item-danger"
            role="menuitem"
            onClick={() => {
              void clearStoredImageGenerationForCurrentUser().finally(() => logout());
            }}
          >
            Log out
          </button>
          <div className="user-profile-menu-divider" />
          <div className="user-profile-theme">
            <ThemePicker value={theme} onChange={onThemeChange} compact />
          </div>
        </div>
      )}

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        theme={theme}
        onThemeChange={onThemeChange}
      />
    </div>
  );
}
