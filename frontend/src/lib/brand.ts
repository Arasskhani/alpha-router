/** Product branding and browser storage keys. */

export const PRODUCT_NAME = "Alpharouter";

/** Claimed mark. Use ® only after a registration certificate is issued. */
export const TRADEMARK_SYMBOL = "™";

export const TRADEMARK_OWNER = "Majid Arasskhani";

export const PRODUCT_NAME_MARKED = `${PRODUCT_NAME}${TRADEMARK_SYMBOL}`;

/** Login page tagline (shown below the Alpharouter wordmark). */
export const LOGIN_TAGLINE = "One route. Every model.";

export const COOKIE_NAMES = {
  session: "alpha_router_session",
  csrf: "alpha_router_csrf",
} as const;

export const STORAGE_KEYS = {
  token: "alpha_router_token",
  role: "alpha_router_role",
  theme: "alpha_router_theme",
  loginAt: "alpha_router_login_at",
  isActive: "alpha_router_is_active",
  chatTools: "alpha_router_chat_tools",
  defaultModel: "alpha_router_default_model",
  privateChats: "alpha_router_private_chats",
  authProvider: "alpha_router_auth_provider",
  adminSidebarOpenSections: "alpha_router_admin_sidebar_open_sections",
  modelsView: "alpha_router_models_view",
  mediaView: "alpha_router_media_view",
} as const;

export const BROWSER_EVENT_NAMES = {
  userPrefsSaved: "alpha-router:user-prefs-saved",
  modelsSyncFlash: "alpha-router:models-sync-flash",
  /** Fired after Settings → Import chats succeeds (additive merge). */
  chatsImported: "alpha-router:chats-imported",
} as const;

export const PAGE_TITLE = `${PRODUCT_NAME_MARKED} | ${LOGIN_TAGLINE}`;
