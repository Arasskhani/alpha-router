import { Link, Outlet, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import AlphaRouterLogo from "./AlphaRouterLogo";
import SidebarNav from "./SidebarNav";
import UserProfile from "./UserProfile";
import { useReadOnly } from "../context/ReadOnlyContext";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { ShellMenuContext } from "../context/ShellMenuContext";
import { PAGE_TITLE } from "../lib/brand";
import {
  applyThemeToDocument,
  loadCachedTheme,
  saveCachedTheme,
  type CachedTheme,
} from "../lib/themeCache";
import { hydrateUserPrefsFromServer, saveThemeToServer } from "../lib/chatStorage";
import { getSessionUser } from "../lib/session";
import type { NavItem, NavSection } from "../nav/types";

type Theme = CachedTheme;

export default function Shell({ nav }: { nav: NavItem[] | NavSection[] }) {
  const loc = useLocation();
  const [theme, setThemeState] = useState<Theme>(() => loadCachedTheme());
  const [navPeek, setNavPeek] = useState(false);

  const path = loc.pathname.replace(/\/$/, "") || "/";
  const isChat = path.endsWith("/chat");
  const isDocs = path.endsWith("/docs") || path.endsWith("/manual");
  const home = path.startsWith("/admin") ? "/admin" : "/app";

  useEffect(() => {
    applyThemeToDocument(theme);
    saveCachedTheme(theme);
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
  }, []);  useEffect(() => {
    document.title = PAGE_TITLE;
  }, []);

  useEffect(() => {
    setNavPeek(false);
  }, [path]);

  const contentClass = isChat
    ? " content--chat"
    : isDocs
      ? " content--docs"
      : path === "/admin" || path === "/app"
        ? " content--dashboard"
        : "";

  const layoutClass = isChat ? " layout--chat" : path === "/admin" || path === "/app" ? " layout--dashboard" : "";

  const readOnly = useReadOnly();

  const sidebarInner = (
    <>
      <Link to={home} className="sidebar-brand">
        <AlphaRouterLogo size={30} className="alpha-router-logo--gradient" />
      </Link>
      <SidebarNav
        nav={nav}
        className="sidebar-nav"
        onNavigate={() => {
          if (isChat) setNavPeek(false);
        }}
      />
    </>
  );

  return (
    <ShellMenuContext.Provider
      value={{
        openAdminMenu: () => {
          if (isChat) setNavPeek(true);
        },
      }}
    >
      <div className={`layout${layoutClass}`}>
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
        ) : (
          <aside className="sidebar">{sidebarInner}</aside>
        )}

        <div className="main-column">
          {readOnly && !isChat && <ReadOnlyBanner />}
          {!isChat && (
            <header className={`app-topbar${isDocs ? " app-topbar--docs" : ""}`}>
              <UserProfile theme={theme} onThemeChange={setTheme} />
            </header>
          )}
          <main className={`content${contentClass}${readOnly && path.startsWith("/admin") ? " admin-write-locked" : ""}`}>
            <Outlet context={{ theme, setTheme }} />
          </main>
        </div>
      </div>
    </ShellMenuContext.Provider>
  );
}
