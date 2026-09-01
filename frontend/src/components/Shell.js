import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import AlphaRouterLogo from "./AlphaRouterLogo";
import ModelProviderIcon from "./ModelProviderIcon";
import SidebarNav from "./SidebarNav";
import TopbarNav from "./TopbarNav";
import { useReadOnly } from "../context/ReadOnlyContext";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { ShellMenuContext } from "../context/ShellMenuContext";
import { ChatModelChromeProvider, useChatModelChromeApi, } from "../context/ChatModelChromeContext";
import { PAGE_TITLE } from "../lib/brand";
import { isProjectWorkspacePath } from "../lib/userPanelNav";
import { applyThemeToDocument, followsSystemPreference, loadCachedTheme, saveCachedTheme, } from "../lib/themeCache";
import { hydrateUserPrefsFromServer, saveThemeToServer } from "../lib/chatStorage";
import { getSessionUser } from "../lib/session";
import usePresenceHeartbeat from "../hooks/usePresenceHeartbeat";
export default function Shell({ nav }) {
    const loc = useLocation();
    const [theme, setThemeState] = useState(() => loadCachedTheme());
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
        if (!followsSystemPreference(theme))
            return;
        const mq = window.matchMedia("(prefers-color-scheme: dark)");
        const onChange = () => applyThemeToDocument(theme);
        mq.addEventListener("change", onChange);
        return () => mq.removeEventListener("change", onChange);
    }, [theme]);
    useEffect(() => {
        if (!getSessionUser())
            return;
        let cancelled = false;
        hydrateUserPrefsFromServer()
            .then((prefs) => {
            if (!cancelled) {
                setThemeState(prefs.theme);
                saveCachedTheme(prefs.theme);
            }
        })
            .catch(() => { });
        return () => {
            cancelled = true;
        };
    }, []);
    const setTheme = useCallback((next) => {
        setThemeState(next);
        saveCachedTheme(next);
        applyThemeToDocument(next);
        if (getSessionUser()) {
            void saveThemeToServer(next).catch(() => { });
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
    const sidebarInner = (_jsx(SidebarNav, { nav: nav, className: "sidebar-nav", onNavigate: () => {
            if (isChat)
                setNavPeek(false);
        } }));
    return (_jsx(ChatModelChromeProvider, { children: _jsx(ShellMenuContext.Provider, { value: {
                openAdminMenu: () => {
                    if (isChat)
                        setNavPeek(true);
                },
            }, children: _jsxs("div", { className: `layout${layoutClass}`, children: [_jsxs("header", { className: "app-topbar", children: [_jsxs("div", { className: "topbar-left", children: [_jsx(Link, { to: home, className: "topbar-brand", children: _jsx(AlphaRouterLogo, { size: 24, showMark: true, joined: true, className: "alpha-router-logo--topbar" }) }), isChat || isProjectWorkspace ? _jsx(TopbarModelSearch, { always: isChat }) : null] }), isChat || isProjectWorkspace ? _jsx(TopbarSelectedModels, { always: isChat }) : null, _jsx(TopbarNav, { theme: theme, onThemeChange: setTheme })] }), _jsxs("div", { className: "layout-body", children: [isChat ? (_jsxs("div", { className: `sidebar-flyout${navPeek ? " sidebar-flyout--open" : ""}`, onMouseLeave: () => setNavPeek(false), children: [_jsx("div", { className: "sidebar-peek-rail", title: "Menus", "aria-label": "Show navigation", onMouseEnter: () => setNavPeek(true) }), _jsx("aside", { className: `sidebar sidebar--flyout${navPeek ? " is-open" : ""}`, onMouseEnter: () => setNavPeek(true), children: sidebarInner })] })) : isProjectWorkspace ? null : (_jsx("aside", { className: "sidebar", children: sidebarInner })), _jsxs("div", { className: "main-column", children: [readOnly && !isChatLayout && _jsx(ReadOnlyBanner, {}), _jsx("main", { className: `content${contentClass}${readOnly && path.startsWith("/admin") ? " admin-write-locked" : ""}`, children: _jsx(Outlet, { context: { theme, setTheme } }) })] })] })] }) }) }));
}
function shortTopbarModelName(name, id) {
    const n = name || id;
    return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}
function TopbarModelSearch({ always = false }) {
    const api = useChatModelChromeApi();
    if (!always && !api)
        return null;
    return (_jsxs("div", { className: "topbar-model-search", children: [_jsxs("button", { type: "button", className: "topbar-model-search__field", onClick: () => api?.openReplacePicker(), disabled: !api?.modelsReady, "aria-label": "Search models", title: "Search models", children: [_jsxs("svg", { viewBox: "0 0 24 24", width: "15", height: "15", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "11", cy: "11", r: "7" }), _jsx("path", { d: "M20 20l-3.5-3.5", strokeLinecap: "round" })] }), _jsx("span", { children: "Search Models" })] }), _jsx("button", { type: "button", className: "topbar-model-search__add", onClick: () => api?.openAppendPicker(), disabled: !api || api.addModelDisabled, "aria-label": api?.addModelAriaLabel || "Add model", title: api?.addModelTitle || "Add model", children: "+" })] }));
}
function TopbarSelectedModels({ always = false }) {
    const api = useChatModelChromeApi();
    if (!always && !api)
        return null;
    if (!api?.selectedModels.length)
        return null;
    return (_jsx("div", { className: "alpha-router-selected-models topbar-selected-models", children: api.selectedModels.map((m) => (_jsxs("span", { className: "alpha-router-model-pill", children: [_jsx(ModelProviderIcon, { modelId: m.external_id || m.id, size: 14 }), _jsx("span", { className: "alpha-router-model-pill__name", title: m.name, children: shortTopbarModelName(m.name, m.id) }), _jsx("button", { type: "button", className: "alpha-router-model-pill__remove", onClick: () => api.onRemoveModel(m.id), "aria-label": `Remove ${m.name}`, children: "\u00D7" })] }, m.id))) }));
}
