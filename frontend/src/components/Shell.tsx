import { Link, Outlet, useLocation } from "react-router-dom";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import RouteErrorBoundary from "./RouteErrorBoundary";
import AlphaRouterLogo from "./AlphaRouterLogo";
import BottomTabBar from "./BottomTabBar";
import InstallBanner from "./InstallBanner";
import UpdateNotice from "./UpdateNotice";
import { useSoftKeyboardOpen } from "../hooks/useSoftKeyboardOpen";
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
import { attachDragScroll } from "../lib/dragScroll";
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
import { NAV_DRAWER_QUERY, useMediaQuery, usePhoneLayout } from "../hooks/useMediaQuery";
import { useVisualViewportHeight } from "../hooks/useVisualViewportHeight";
import type { NavItem, NavSection } from "../nav/types";

type Theme = CachedTheme;

/**
 * Whether an Escape press is for a layer above the drawers: a dialog or a menu
 * that is open (they listen for it themselves), or a search field with text,
 * whose first Escape clears the field.
 */
function escapeBelongsElsewhere(target: EventTarget | null): boolean {
  if (document.querySelector('[aria-modal="true"], [role="menu"]')) return true;
  return target instanceof HTMLInputElement && target.type === "search" && target.value !== "";
}

export default function Shell({ nav }: { nav: NavItem[] | NavSection[] }) {
  const loc = useLocation();
  const [theme, setThemeState] = useState<Theme>(() => loadCachedTheme());
  const [navPeek, setNavPeek] = useState(false);
  // Phone: the side panel is a drawer behind the topbar's menu button. On the
  // chat page that panel is the chat history (ChatPanel renders it and reads
  // the state through ShellMenuContext); elsewhere it is the navigation here.
  const phone = usePhoneLayout();
  // Up to 1024px (tablets too) the navigation is a drawer outside the chat
  // pages; a tablet's chat pages keep their desktop layout (drawerLayout below).
  const navDrawerWidth = useMediaQuery(NAV_DRAWER_QUERY);
  // The layout's height follows the visual viewport, so the iOS keyboard does not cover the composer.
  useVisualViewportHeight(phone);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // How many mounted panels own the drawer (the chat history claims it).
  const [drawerClaims, setDrawerClaims] = useState(0);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const flyoutRef = useRef<HTMLElement>(null);
  // What had focus when the navigation flyout opened; it gets it back on close.
  const flyoutOpenerRef = useRef<HTMLElement | null>(null);

  // Shell wraps every authenticated page, so this is the single mount point.
  usePresenceHeartbeat();

  const path = loc.pathname.replace(/\/$/, "") || "/";
  const isChat = path.endsWith("/chat");
  const isProjectWorkspace = isProjectWorkspacePath(path);
  const isChatLayout = isChat || isProjectWorkspace;
  const isDocs = path.endsWith("/docs") || path.endsWith("/manual");
  const home = path.startsWith("/admin") ? "/admin" : "/app";
  // Whether the side panel is a drawer behind the menu button: on a phone
  // always, on a tablet outside the chat pages.
  const drawerLayout = phone || (navDrawerWidth && !isChatLayout);

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
    setDrawerOpen(false);
  }, [path]);

  // Leaving the drawer layout (a rotation, a resized window) puts the panel
  // back in the page; an "open drawer" would otherwise linger invisibly and
  // show itself on the next rotation back.
  const [wasDrawerLayout, setWasDrawerLayout] = useState(drawerLayout);
  if (wasDrawerLayout !== drawerLayout) {
    setWasDrawerLayout(drawerLayout);
    setDrawerOpen(false);
    setNavPeek(false);
  }

  useEffect(() => {
    if (!drawerLayout || (!drawerOpen && !navPeek)) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || escapeBelongsElsewhere(event.target)) return;
      // Navigation on top of the chat history closes first, like a stacked dialog.
      if (navPeek) setNavPeek(false);
      else setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerLayout, drawerOpen, navPeek]);

  // Focus follows the drawer in, and comes back to the button that opened it.
  const drawerWasOpen = useRef(false);
  useEffect(() => {
    if (!drawerLayout) return;
    if (drawerOpen) {
      drawerRef.current?.focus({ preventScroll: true });
    } else if (drawerWasOpen.current) {
      menuButtonRef.current?.focus({ preventScroll: true });
    }
    drawerWasOpen.current = drawerOpen;
  }, [drawerLayout, drawerOpen]);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const claimDrawer = useCallback(() => {
    setDrawerClaims((n) => n + 1);
    return () => setDrawerClaims((n) => n - 1);
  }, []);
  // The flyout it opens only exists on the chat page; elsewhere the flag is
  // inert and cleared on the next navigation.
  const openAdminMenu = useCallback(() => {
    flyoutOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setNavPeek(true);
  }, []);
  // One object per change, not per render: ChatPanel's claim effect depends on it.
  const shellMenu = useMemo(
    () => ({ openAdminMenu, phone, drawerOpen: phone && drawerOpen, closeDrawer, claimDrawer }),
    [openAdminMenu, phone, drawerOpen, closeDrawer, claimDrawer],
  );

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
  // The bottom edge's owner in an installed app: the tab bar pads itself for the
  // home indicator; otherwise the layout does, unless the keyboard is up.
  const hasTabBar = phone && (path === "/app" || path.startsWith("/app/"));
  const layoutRef = useRef<HTMLDivElement>(null);

  const sidebarInner = (
    <SidebarNav
      nav={nav}
      className="sidebar-nav"
      onNavigate={() => {
        if (isChat) setNavPeek(false);
        setDrawerOpen(false);
      }}
    />
  );

  // In the drawer layout the menu button opens the navigation drawer, unless
  // a page panel (the chat history, on a phone) has claimed it. The
  // navigation flyout can open over that panel. A backdrop closes whichever
  // is on top on tap.
  const navDrawer = drawerLayout && (!isChatLayout || drawerClaims === 0);
  const navDrawerOpen = navDrawer && drawerOpen;
  const navFlyoutOpen = phone && isChat && navPeek;
  const anythingOpen = (drawerLayout && drawerOpen) || navFlyoutOpen;

  // On a phone the flyout is a layer of its own: focus goes in with it and
  // back to whatever opened it afterwards.
  const flyoutWasOpen = useRef(false);
  useEffect(() => {
    if (navFlyoutOpen) {
      flyoutRef.current?.focus({ preventScroll: true });
    } else if (flyoutWasOpen.current) {
      flyoutOpenerRef.current?.focus({ preventScroll: true });
      flyoutOpenerRef.current = null;
    }
    flyoutWasOpen.current = navFlyoutOpen;
  }, [navFlyoutOpen]);

  return (
    <ChatModelChromeProvider>
      <ShellMenuContext.Provider value={shellMenu}>
        <div ref={layoutRef} className={`layout${layoutClass}${hasTabBar ? " layout--has-tabbar" : ""}`}>
          <SoftKeyboardMarker target={layoutRef} />
          <header className="app-topbar">
            <div className="topbar-left">
              {drawerLayout ? (
                <button
                  ref={menuButtonRef}
                  type="button"
                  className="topbar-menu-btn"
                  aria-label={anythingOpen ? "Close menu" : "Open menu"}
                  aria-expanded={anythingOpen}
                  aria-controls="shell-drawer"
                  onClick={() => {
                    // With the navigation open over the history, the button
                    // means "close all of it", not "toggle the layer underneath".
                    if (navPeek) {
                      setNavPeek(false);
                      setDrawerOpen(false);
                    } else {
                      setDrawerOpen((open) => !open);
                    }
                  }}
                >
                  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden>
                    <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </button>
              ) : null}
              <Link to={home} className="topbar-brand">
                <AlphaRouterLogo
                  size={24}
                  showMark
                  joined
                  markOnly={phone}
                  className="alpha-router-logo--topbar"
                />
              </Link>
              {isChat || isProjectWorkspace ? <TopbarModelSearch always={isChat} /> : null}
            </div>
            {isChat || isProjectWorkspace ? <TopbarSelectedModels always={isChat} /> : null}
            <TopbarNav theme={theme} onThemeChange={setTheme} />
          </header>

          <div className="layout-body">
            {navDrawerOpen || navFlyoutOpen ? (
              <div
                className={`shell-drawer-backdrop${navFlyoutOpen ? " shell-drawer-backdrop--over" : ""}`}
                aria-hidden
                onClick={() => {
                  // Like stacked dialogs: a tap outside closes the top layer only.
                  if (navPeek) setNavPeek(false);
                  else setDrawerOpen(false);
                }}
              />
            ) : null}
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
                  ref={flyoutRef}
                  className={`sidebar sidebar--flyout${navPeek ? " is-open" : ""}`}
                  tabIndex={-1}
                  aria-hidden={navPeek ? undefined : true}
                  onMouseEnter={() => setNavPeek(true)}
                >
                  {sidebarInner}
                </aside>
              </div>
            ) : null}
            {!isChatLayout || navDrawer ? (
              <aside
                ref={drawerRef}
                id="shell-drawer"
                className={`sidebar${drawerLayout ? " sidebar--drawer" : ""}${navDrawerOpen ? " is-open" : ""}`}
                tabIndex={drawerLayout ? -1 : undefined}
                aria-hidden={drawerLayout && !navDrawerOpen ? true : undefined}
              >
                {sidebarInner}
              </aside>
            ) : null}

            <div className="main-column">
              {readOnly && !isChatLayout && <ReadOnlyBanner />}
              <main className={`content${contentClass}${readOnly && path.startsWith("/admin") ? " admin-write-locked" : ""}`}>
                <RouteErrorBoundary resetKey={path}>
                  <Suspense fallback={<div className="app-loading">Loading…</div>}>
                    <Outlet context={{ theme, setTheme }} />
                  </Suspense>
                </RouteErrorBoundary>
              </main>
            </div>
          </div>
          <UpdateNotice />
          <InstallBanner />
          {hasTabBar ? <BottomTabBar /> : null}
        </div>
      </ShellMenuContext.Provider>
    </ChatModelChromeProvider>
  );
}

/**
 * Marks the layout with data-soft-keyboard while the on-screen keyboard is up.
 * A component of its own, so focusing a field re-renders it and not the page.
 */
function SoftKeyboardMarker({ target }: { target: React.RefObject<HTMLElement | null> }) {
  const open = useSoftKeyboardOpen();
  useEffect(() => {
    target.current?.toggleAttribute("data-soft-keyboard", open);
  }, [open, target]);
  return null;
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

/** A mouse wheel over a row that scrolls sideways turns it, as a trackpad's swipe would. */
function turnWheelSideways(event: React.WheelEvent<HTMLElement>) {
  const row = event.currentTarget;
  if (row.scrollWidth <= row.clientWidth || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
  row.scrollLeft += getComputedStyle(row).direction === "rtl" ? -event.deltaY : event.deltaY;
}

function TopbarSelectedModels({ always = false }: { always?: boolean }) {
  const api = useChatModelChromeApi();
  const count = api?.selectedModels.length ?? 0;
  // Pills that do not fit scroll sideways (styles.css). A mouse can pull the
  // row and turn it with the wheel, and a model just added is brought into view.
  const rowRef = useRef<HTMLDivElement | null>(null);
  const releaseDragRef = useRef<(() => void) | null>(null);
  const setRow = useCallback((row: HTMLDivElement | null) => {
    releaseDragRef.current?.();
    releaseDragRef.current = row ? attachDragScroll(row) : null;
    rowRef.current = row;
  }, []);
  // Added to the models already there, not the first ones to arrive (the row starts at its start).
  const countBefore = useRef(count);
  useEffect(() => {
    if (countBefore.current > 0 && count > countBefore.current) {
      rowRef.current?.lastElementChild?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    countBefore.current = count;
  }, [count]);
  if (!always && !api) return null;
  if (!api?.selectedModels.length) return null;
  return (
    <div ref={setRow} className="alpha-router-selected-models topbar-selected-models" onWheel={turnWheelSideways}>
      {api.selectedModels.map((m) => (
        // The whole pill names its model, its icon too: a squeezed pill may show no name at all.
        <span key={m.id} className="alpha-router-model-pill" title={m.name}>
          <ModelProviderIcon modelId={m.external_id || m.id} size={14} title={m.name} />
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
