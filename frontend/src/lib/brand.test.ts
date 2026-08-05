import { describe, expect, it } from "vitest";
import {
  ATTACHMENT_MESSAGE_PREFIX,
  AUDIO_MESSAGE_PREFIX,
} from "./chatAttachments";
import { IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER } from "./chatImage";
import {
  BROWSER_EVENT_NAMES,
  COOKIE_NAMES,
  PAGE_TITLE,
  PRODUCT_NAME,
  STORAGE_KEYS,
} from "./brand";
import {
  CHAT_LEADER_LOCK_NAME,
  CHAT_REFRESH_EVENT_NAME,
  CHAT_SYNC_CHANNEL_NAME,
} from "./chatLeader";
import { PRIVATE_MEDIA_DB_NAME } from "./privateMediaStore";

describe("project-owned naming contracts", () => {
  it("locks the product display identity", () => {
    expect(PRODUCT_NAME).toBe("Alpha Router");
    expect(PAGE_TITLE).toBe("Alpha Router | turning ideas into reality...");
  });

  it("locks browser storage names", () => {
    expect(STORAGE_KEYS).toEqual({
      token: "alpha_router_token",
      role: "alpha_router_role",
      theme: "alpha_router_theme",
      loginAt: "alpha_router_login_at",
      isActive: "alpha_router_is_active",
      chatTools: "alpha_router_chat_tools",
      defaultModel: "alpha_router_default_model",
      privateChats: "alpha_router_private_chats",
      privatePersist: "alpha_router_private_persist",
      authProvider: "alpha_router_auth_provider",
      adminSidebarOpenSections: "alpha_router_admin_sidebar_open_sections",
      modelsView: "alpha_router_models_view",
      mediaView: "alpha_router_media_view",
    });
  });

  it("locks project-owned browser event names", () => {
    expect(BROWSER_EVENT_NAMES).toEqual({
      userPrefsSaved: "alpha-router:user-prefs-saved",
      modelsSyncFlash: "alpha-router:models-sync-flash",
    });
  });

  it("locks browser authentication cookie names", () => {
    expect(COOKIE_NAMES).toEqual({
      session: "alpha_router_session",
      csrf: "alpha_router_csrf",
    });
  });

  it("locks persisted chat wire markers", () => {
    expect(IMAGE_MESSAGE_PREFIX).toBe("__ALPHA_ROUTER_IMAGE_JSON__:");
    expect(IMAGE_PENDING_MARKER).toBe("__ALPHA_ROUTER_IMAGE_PENDING__");
    expect(ATTACHMENT_MESSAGE_PREFIX).toBe("__ALPHA_ROUTER_ATTACH_JSON__:");
    expect(AUDIO_MESSAGE_PREFIX).toBe("__ALPHA_ROUTER_AUDIO_JSON__:");
  });

  it("locks chat and media browser persistence identifiers", () => {
    expect(PRIVATE_MEDIA_DB_NAME).toBe("alpha_router_private_media");
    expect(CHAT_SYNC_CHANNEL_NAME).toBe("alpha_router_chat_sync");
    expect(CHAT_LEADER_LOCK_NAME).toBe("alpha_router_chat_leader");
    expect(CHAT_REFRESH_EVENT_NAME).toBe("alpha_router_chat_refresh");
  });
});
