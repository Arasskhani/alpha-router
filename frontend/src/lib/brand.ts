/** Product branding and browser storage keys. */

export const PRODUCT_NAME = "NITRO";

/** Login page tagline (shown below the NITRO wordmark) */
export const LOGIN_TAGLINE = "turning ideas into reality...";

export const STORAGE_KEYS = {
  token: "nitro_token",
  role: "nitro_role",
  theme: "nitro_theme",
  loginAt: "nitro_login_at",
  isActive: "nitro_is_active",
  chatTools: "nitro_chat_tools",
  defaultModel: "nitro_default_model",
  privateChats: "nitro_private_chats",
  authProvider: "nitro_auth_provider",
} as const;

export const PAGE_TITLE = `${PRODUCT_NAME} | ${LOGIN_TAGLINE}`;
