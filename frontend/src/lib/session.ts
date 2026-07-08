import { STORAGE_KEYS } from "./brand";

/** Copy legacy localStorage keys once after rebrand (billi_* → nitro_*). */
export function migrateLegacyStorageKeys() {
  const legacy: Record<string, string> = {
    nitro_token: "billi_token",
    nitro_role: "billi_role",
    nitro_theme: "billi_theme",
    nitro_login_at: "billi_login_at",
    nitro_is_active: "billi_is_active",
  };
  for (const [nitroKey, billiKey] of Object.entries(legacy)) {
    if (!localStorage.getItem(nitroKey)) {
      const v = localStorage.getItem(billiKey);
      if (v) localStorage.setItem(nitroKey, v);
    }
    localStorage.removeItem(billiKey);
  }
}

export function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getSessionUser(): { username: string; role: string; loginAt: number } | null {
  const token = localStorage.getItem(STORAGE_KEYS.token);
  if (!token) return null;
  const payload = parseJwtPayload(token);
  const loginAt = Number(localStorage.getItem(STORAGE_KEYS.loginAt));
  return {
    username: (payload?.sub as string) || "User",
    role: localStorage.getItem(STORAGE_KEYS.role) || (payload?.role as string) || "user",
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

export function logout() {
  localStorage.removeItem(STORAGE_KEYS.chatTools);
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.role);
  localStorage.removeItem(STORAGE_KEYS.loginAt);
  localStorage.removeItem(STORAGE_KEYS.isActive);
  // Keep STORAGE_KEYS.theme — device cache for login page before auth.
  window.location.href = "/login";
}
