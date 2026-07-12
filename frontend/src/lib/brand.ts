/** Product branding and browser storage keys. */

export const PRODUCT_NAME = "Alpha Router";

/** Login page tagline (shown below the Alpha Router wordmark) */
export const LOGIN_TAGLINE = "turning ideas into reality...";

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
} as const;

export const PAGE_TITLE = `${PRODUCT_NAME} | ${LOGIN_TAGLINE}`;
