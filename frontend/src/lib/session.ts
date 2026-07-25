import { STORAGE_KEYS } from "./brand";
import { authFetch, clearCachedSession, getCachedSession } from "../api";
import { clearPrivateMediaStore } from "./privateMediaStore";

/** Copy legacy localStorage keys once after rebrand (alpha_router_* → alpha_router_*). */
export function migrateLegacyStorageKeys() {
  const legacy: Record<string, string> = {
    alpha_router_theme: "alpha_router_theme",
    alpha_router_login_at: "alpha_router_login_at",
    alpha_router_is_active: "alpha_router_is_active",
  };
  for (const [alphaRouterKey, alphaRouterKey] of Object.entries(legacy)) {
    if (!localStorage.getItem(alphaRouterKey)) {
      const v = localStorage.getItem(alphaRouterKey);
      if (v) localStorage.setItem(alphaRouterKey, v);
    }
    localStorage.removeItem(alphaRouterKey);
  }
  localStorage.removeItem("alpha_router_token");
  localStorage.removeItem("alpha_router_role");
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.role);
}

export function getSessionUser(): { username: string; role: string; loginAt: number } | null {
  const session = getCachedSession();
  if (!session) return null;
  const loginAt = Number(localStorage.getItem(STORAGE_KEYS.loginAt));
  return {
    username: session.username || "User",
    role: session.role || "user",
    loginAt: loginAt > 0 ? loginAt : Date.now(),
  };
}

export function formatSessionDuration(loginAt: number): string {
  const sec = Math.floor((Date.now() - loginAt) / 1000);
  if (sec < 60) return "Just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  if (hr < 24) return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
  const days = Math.floor(hr / 24);
  const remHr = hr % 24;
  return remHr > 0 ? `${days}d ${remHr}h` : `${days}d`;
}

export function setSessionActive(isActive: boolean) {
  localStorage.setItem(STORAGE_KEYS.isActive, isActive ? "1" : "0");
}

export function isSessionActive(): boolean {
  return localStorage.getItem(STORAGE_KEYS.isActive) !== "0";
}

export function markLoggedIn(isActive = true) {
  localStorage.setItem(STORAGE_KEYS.loginAt, String(Date.now()));
  setSessionActive(isActive);
}

import { getMyActivityPath as rbacMyActivityPath } from "./rbac";

export function getMyActivityPath(role: string): string {
  return rbacMyActivityPath(role);
}

export async function logout() {
  const session = getCachedSession();
  const provider = session?.auth_provider || localStorage.getItem(STORAGE_KEYS.authProvider);
  // Server-side revocation: bump the user's token_version so the current JWT
  // (and any stolen copy) is rejected from now on. Best-effort — we clear
  // local state regardless of whether this call succeeds.
  try {
    await authFetch("/api/auth/logout", { method: "POST" });
  } catch {
    /* network error — proceed to clear local state anyway */
  }
  if (localStorage.getItem("alpha_router_private_persist") !== "1") {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(`${STORAGE_KEYS.privateChats}:`)) localStorage.removeItem(key);
    }
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith(`${STORAGE_KEYS.privateChats}:msgcache:`)) sessionStorage.removeItem(key);
    }
    try {
      await clearPrivateMediaStore();
    } catch {
      /* best-effort browser cleanup */
    }
  }
  clearCachedSession();
  localStorage.removeItem(STORAGE_KEYS.chatTools);
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.role);
  localStorage.removeItem(STORAGE_KEYS.loginAt);
  localStorage.removeItem(STORAGE_KEYS.isActive);
  localStorage.removeItem(STORAGE_KEYS.authProvider);
  // Keep STORAGE_KEYS.theme — device cache for login page before auth.
  // For SSO users, also terminate the IdP session when available.
  if (provider === "saml") {
    window.location.href = "/api/auth/saml/logout";
    return;
  }
  if (provider === "oidc") {
    window.location.href = "/api/auth/oidc/logout";
    return;
  }
  window.location.href = "/login";
}
