import { Link, Outlet, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import AlphaRouterLogo from "./AlphaRouterLogo";
import ModelProviderIcon from "./ModelProviderIcon";
import SidebarNav from "./SidebarNav";
import TopbarNav from "./TopbarNav";
import { useReadOnly } from "../context/ReadOnlyContext";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { ShellMenuContext } from "../context/ShellMenuContext";
import {
  ChatModelChromeProvider,
  useChatModelChromeApi,
} from "../context/ChatModelChromeContext";
import { PAGE_TITLE } from "../lib/brand";
import { isProjectWorkspacePath } from "../lib/userPanelNav";
import {
  applyThemeToDocument,
  followsSystemPreference,
  loadCachedTheme,
  saveCachedTheme,
  type CachedTheme,
} from "../lib/themeCache";
import { hydrateUserPrefsFromServer, saveThemeToServer } from "../lib/chatStorage";
import { getSessionUser } from "../lib/session";
import usePresenceHeartbeat from "../hooks/usePresenceHeartbeat";
import type { NavItem, NavSection } from "../nav/types";

type Theme = CachedTheme;

export default function Shell({ nav }: { nav: NavItem[] | NavSection[] }) {
  const loc = useLocation();
  const [theme, setThemeState] = useState<Theme>(() => loadCachedTheme());
  const [navPeek, setNavPeek] = useState(false);

  // Shell wraps every authenticated page, so this is the single mount point.
  usePresenceHeartbeat();

  const path = loc.pathname.replace(/\/$/, "") || "/";
  const isChat = path.endsWith("/chat");
  const isProjectWorkspace = isProjectWorkspacePath(path);
  const isChatLayout = isChat || isProjectWorkspace;
  const isDocs = path.endsWith("/docs") || path.endsWith("/manual");
  const home = path.startsWith("/admin") ? "/admin" : "/app";

  useEffect(() => {
    applyThemeToDocument(theme);
    saveCachedTheme(theme);
    if (!followsSystemPreference(theme)) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyThemeToDocument(theme);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  useEffect(() => {
    if (!getSessionUser()) return;
    let cancelled = false;
    hydrateUserPrefsFromServer()
      .then((prefs) => {
        if (!cancelled) {
          setThemeState(prefs.theme);
          saveCachedTheme(prefs.theme);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    saveCachedTheme(next);
    applyThemeToDocument(next);
    if (getSessionUser()) {
      void saveThemeToServer(next).catch(() => {});
    }
  }, []);
  useEffect(() => {
    document.title = PAGE_TITLE;
  }, []);

  useEffect(() => {
    setNavPeek(false);
  }, [path]);

  const contentClass = isChatLayout
    ? " content--chat"
    : isDocs
      ? " content--docs"
      : path === "/admin" || path === "/app"
        ? " content--dashboard"
        : "";

  const layoutClass = isChatLayout
    ? " layout--chat"
    : path === "/admin" || path === "/app"
      ? " layout--dashboard"
      : "";

  const readOnly = useReadOnly();

  const sidebarInner = (
    <SidebarNav
      nav={nav}
      className="sidebar-nav"
      onNavigate={() => {
        if (isChat) setNavPeek(false);
      }}
    />
  );

  return (
    <ChatModelChromeProvider>
      <ShellMenuContext.Provider
        value={{
          openAdminMenu: () => {
            if (isChat) setNavPeek(true);
          },
        }}
      >
        <div className={`layout${layoutClass}`}>
          <header className="app-topbar">
            <div className="topbar-left">
              <Link to={home} className="topbar-brand">
                <AlphaRouterLogo size={24} showMark joined className="alpha-router-logo--topbar" />
              </Link>
              {isChat || isProjectWorkspace ? <TopbarModelSearch always={isChat} /> : null}
            </div>
            {isChat || isProjectWorkspace ? <TopbarSelectedModels always={isChat} /> : null}
            <TopbarNav theme={theme} onThemeChange={setTheme} />
          </header>

          <div className="layout-body">
            {isChat ? (
              <div
                className={`sidebar-flyout${navPeek ? " sidebar-flyout--open" : ""}`}
                onMouseLeave={() => setNavPeek(false)}
              >
                <div
                  className="sidebar-peek-rail"
                  title="Menus"
                  aria-label="Show navigation"
                  onMouseEnter={() => setNavPeek(true)}
                />
                <aside
                  className={`sidebar sidebar--flyout${navPeek ? " is-open" : ""}`}
                  onMouseEnter={() => setNavPeek(true)}
                >
                  {sidebarInner}
                </aside>
              </div>
            ) : isProjectWorkspace ? null : (
              <aside className="sidebar">{sidebarInner}</aside>
            )}

            <div className="main-column">
              {readOnly && !isChatLayout && <ReadOnlyBanner />}
              <main className={`content${contentClass}${readOnly && path.startsWith("/admin") ? " admin-write-locked" : ""}`}>
                <Outlet context={{ theme, setTheme }} />
              </main>
            </div>
          </div>
        </div>
      </ShellMenuContext.Provider>
    </ChatModelChromeProvider>
  );
}

function shortTopbarModelName(name: string, id: string) {
  const n = name || id;
  return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}

function TopbarModelSearch({ always = false }: { always?: boolean }) {
  const api = useChatModelChromeApi();
  if (!always && !api) return null;
  return (
    <div className="topbar-model-search">
      <button
        type="button"
        className="topbar-model-search__field"
        onClick={() => api?.openReplacePicker()}
        disabled={!api?.modelsReady}
        aria-label="Search models"
        title="Search models"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
        </svg>
        <span>Search Models</span>
      </button>
      <button
        type="button"
        className="topbar-model-search__add"
        onClick={() => api?.openAppendPicker()}
        disabled={!api || api.addModelDisabled}
        aria-label={api?.addModelAriaLabel || "Add model"}
        title={api?.addModelTitle || "Add model"}
      >
        +
      </button>
    </div>
  );
}

function TopbarSelectedModels({ always = false }: { always?: boolean }) {
  const api = useChatModelChromeApi();
  if (!always && !api) return null;
  if (!api?.selectedModels.length) return null;
  return (
    <div className="alpha-router-selected-models topbar-selected-models">
      {api.selectedModels.map((m) => (
        <span key={m.id} className="alpha-router-model-pill">
          <ModelProviderIcon modelId={m.external_id || m.id} size={14} />
          <span className="alpha-router-model-pill__name" title={m.name}>
            {shortTopbarModelName(m.name, m.id)}
          </span>
          <button
            type="button"
            className="alpha-router-model-pill__remove"
            onClick={() => api.onRemoveModel(m.id)}
            aria-label={`Remove ${m.name}`}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
