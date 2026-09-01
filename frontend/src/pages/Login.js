import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import AlphaRouterLogo from "../components/AlphaRouterLogo";
import { LOGIN_TAGLINE, PAGE_TITLE, PRODUCT_NAME_MARKED, TRADEMARK_OWNER } from "../lib/brand";
import { applyThemeToDocument } from "../lib/themeCache";
import { markLoggedIn } from "../lib/session";
import { isAdminPanelRole, normalizeRole, filterAdminNav, firstAllowedAdminPath } from "../lib/rbac";
import { adminNavSections } from "../nav/adminNav";
import { authFetch, bootstrapSession } from "../api";
function FeatureProvidersArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("circle", { cx: "22", cy: "28", r: "8", fill: "color-mix(in srgb, var(--accent) 14%, transparent)", stroke: "var(--accent)", strokeWidth: "1.2" }), _jsx("circle", { cx: "58", cy: "16", r: "6", fill: "var(--surface)", stroke: "var(--border)", strokeWidth: "1.2" }), _jsx("circle", { cx: "58", cy: "40", r: "6", fill: "var(--surface)", stroke: "var(--border)", strokeWidth: "1.2" }), _jsx("path", { d: "M30 24 L52 18 M30 32 L52 38", stroke: "var(--muted)", strokeWidth: "1.2", strokeLinecap: "round" })] }));
}
function FeatureChatMediaArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("rect", { x: "8", y: "10", width: "44", height: "28", rx: "8", fill: "color-mix(in srgb, var(--accent) 12%, transparent)", stroke: "var(--accent)", strokeWidth: "1.2" }), _jsx("path", { d: "M16 38 L24 48 L24 38 Z", fill: "color-mix(in srgb, var(--accent) 18%, transparent)", stroke: "var(--accent)", strokeWidth: "1" }), _jsx("rect", { x: "48", y: "16", width: "24", height: "20", rx: "4", fill: "var(--surface)", stroke: "var(--border)", strokeWidth: "1.2" }), _jsx("circle", { cx: "56", cy: "24", r: "3", fill: "var(--accent)", opacity: "0.5" }), _jsx("path", { d: "M52 30 H68", stroke: "var(--muted)", strokeWidth: "1.2", strokeLinecap: "round" })] }));
}
function FeatureAdminArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("rect", { x: "10", y: "12", width: "60", height: "36", rx: "6", fill: "color-mix(in srgb, var(--accent) 10%, transparent)", stroke: "var(--border)", strokeWidth: "1.2" }), _jsx("circle", { cx: "24", cy: "26", r: "6", fill: "var(--surface)", stroke: "var(--accent)", strokeWidth: "1.2" }), _jsx("path", { d: "M36 22 H62 M36 30 H54 M36 38 H58", stroke: "var(--muted)", strokeWidth: "1.4", strokeLinecap: "round" })] }));
}
function FeatureApiArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("rect", { x: "14", y: "16", width: "52", height: "24", rx: "6", fill: "color-mix(in srgb, var(--accent) 14%, transparent)", stroke: "var(--accent)", strokeWidth: "1.2" }), _jsx("path", { d: "M28 28 H52", stroke: "var(--accent)", strokeWidth: "2", strokeLinecap: "round" }), _jsx("path", { d: "M34 22 L28 28 L34 34 M46 22 L52 28 L46 34", stroke: "var(--accent)", strokeWidth: "1.6", strokeLinecap: "round", strokeLinejoin: "round", fill: "none" })] }));
}
function FeatureMetricsArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("polyline", { points: "10,42 26,30 40,34 54,18 70,24", fill: "none", stroke: "var(--accent)", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }), _jsx("polyline", { points: "10,28 28,32 44,22 60,36 70,30", fill: "none", stroke: "#22c55e", strokeWidth: "1.5", opacity: "0.75", strokeLinecap: "round", strokeLinejoin: "round" })] }));
}
function FeatureSecurityArt() {
    return (_jsxs("svg", { className: "login-highlight__art login-highlight__svg", viewBox: "0 0 80 56", "aria-hidden": true, children: [_jsx("path", { d: "M40 10 L62 20 V38 C62 48 40 54 40 54 C40 54 18 48 18 38 V20 Z", fill: "color-mix(in srgb, var(--accent) 14%, transparent)", stroke: "var(--accent)", strokeWidth: "1.2" }), _jsx("circle", { cx: "34", cy: "36", r: "4", fill: "var(--surface)", stroke: "var(--border)" }), _jsx("circle", { cx: "40", cy: "36", r: "4", fill: "var(--surface)", stroke: "var(--border)" }), _jsx("circle", { cx: "46", cy: "36", r: "4", fill: "var(--surface)", stroke: "var(--border)" })] }));
}
const LOGIN_HIGHLIGHTS = [
    {
        title: "Many models, one platform",
        desc: "Connect providers once, sync the catalog, and reach every model from a single control plane.",
        art: _jsx(FeatureProvidersArt, {}),
    },
    {
        title: "Chat & media built in",
        desc: "Team chat, image generation, folders, and a shared media library — no external UI required.",
        art: _jsx(FeatureChatMediaArt, {}),
    },
    {
        title: "Full admin control plane",
        desc: "Users, groups, roles, plans, connections, storage, reports, and operations in /admin.",
        art: _jsx(FeatureAdminArt, {}),
    },
    {
        title: "Budgets & visibility",
        desc: "Plan-based limits, per-user budgets, dashboards, and API logs for every request.",
        art: _jsx(FeatureMetricsArt, {}),
    },
    {
        title: "Enterprise access",
        desc: "Local accounts, LDAP/AD, SAML & OIDC SSO, optional TOTP 2FA, and scoped RBAC for every admin menu.",
        art: _jsx(FeatureSecurityArt, {}),
    },
    {
        title: "Optional /v1 API",
        desc: "OpenAI-compatible gateway for IDEs, scripts, and automation — same models and budgets.",
        art: _jsx(FeatureApiArt, {}),
    },
];
async function finishLogin(nav) {
    const session = await bootstrapSession(true);
    const active = session.is_active !== false;
    markLoggedIn(active);
    if (isAdminPanelRole(session.role)) {
        const role = normalizeRole(session.role);
        nav(firstAllowedAdminPath(filterAdminNav(adminNavSections, role)));
    }
    else {
        nav("/app/chat");
    }
}
export default function Login() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [totpCode, setTotpCode] = useState("");
    const [pendingToken, setPendingToken] = useState(null);
    const [error, setError] = useState("");
    const [shakeFields, setShakeFields] = useState(false);
    const [methods, setMethods] = useState({ ldap: false, saml: false, oidc: false });
    const nav = useNavigate();
    const [params] = useSearchParams();
    function triggerCredentialShake() {
        // Retrigger the animation when consecutive failures occur.
        setShakeFields(false);
        requestAnimationFrame(() => setShakeFields(true));
    }
    useEffect(() => {
        document.title = PAGE_TITLE;
        // Pre-auth: theme comes from local device cache only (no server / no user prefs).
        applyThemeToDocument();
        document.body.classList.add("login-route");
        return () => document.body.classList.remove("login-route");
    }, []);
    useEffect(() => {
        authFetch("/api/auth/methods").then((r) => r.json()).then(setMethods).catch(() => { });
    }, []);
    useEffect(() => {
        // SSO callbacks deliver a one-time exchange code (NOT the JWT itself) via
        // ?code=. We POST it to /api/auth/sso/exchange to obtain the session,
        // keeping the token out of the URL/history/Referer/logs.
        const code = params.get("code");
        if (!code)
            return;
        let cancelled = false;
        (async () => {
            try {
                const res = await authFetch("/api/auth/sso/exchange", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ code }),
                });
                if (!res.ok) {
                    const raw = await res.text();
                    let detail = "";
                    try {
                        detail = JSON.parse(raw).detail || "";
                    }
                    catch {
                        detail = raw || "";
                    }
                    if (!cancelled)
                        setError(detail || "SSO login expired, please try again.");
                    return;
                }
                await res.json();
                if (cancelled)
                    return;
                await finishLogin(nav);
            }
            catch {
                if (!cancelled)
                    setError("Cannot reach backend. Make sure backend is running on port 8080.");
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [params, nav]);
    async function onSubmit(e) {
        e.preventDefault();
        setError("");
        try {
            if (pendingToken) {
                const res = await authFetch("/api/auth/login/2fa", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ pending_token: pendingToken, code: totpCode.trim() }),
                });
                if (!res.ok) {
                    const raw = await res.text();
                    let detail = "";
                    try {
                        detail = JSON.parse(raw).detail || "";
                    }
                    catch {
                        detail = raw || "";
                    }
                    throw new Error(detail || "Invalid authentication code");
                }
                await res.json();
                setPendingToken(null);
                setTotpCode("");
                await finishLogin(nav);
                return;
            }
            const res = await authFetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: username.trim(), password }),
            });
            if (!res.ok) {
                const raw = await res.text();
                let detail = "";
                try {
                    const j = JSON.parse(raw);
                    detail = j.detail || j.message || "";
                }
                catch {
                    detail = raw || "";
                }
                if (res.status === 401)
                    throw new Error("Invalid username or password");
                if (res.status === 503) {
                    throw new Error(detail || "LDAP directory is not available right now. Please try again later or use a local account.");
                }
                throw new Error(detail || `Login failed (${res.status})`);
            }
            const data = (await res.json());
            if (data.requires_2fa && data.pending_token) {
                setPendingToken(data.pending_token);
                setTotpCode("");
                return;
            }
            await finishLogin(nav);
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            if (msg === "Failed to fetch") {
                setError("Cannot reach backend. Make sure backend is running on port 8080.");
                return;
            }
            setError(msg || "Login failed");
            triggerCredentialShake();
        }
    }
    return (_jsxs("div", { className: "login-page", children: [_jsx("div", { className: "login-page__mesh", "aria-hidden": true }), _jsx("div", { className: "login-page__glow login-page__glow--a", "aria-hidden": true }), _jsx("div", { className: "login-page__glow login-page__glow--b", "aria-hidden": true }), _jsxs("div", { className: "login-page__shell", children: [_jsxs("section", { className: "login-brand", "aria-label": PRODUCT_NAME_MARKED, children: [_jsxs("div", { className: "login-brand__head", children: [_jsx("h1", { className: "login-brand__title login-brand__title--assemble", children: _jsx(AlphaRouterLogo, { size: 56, showMark: true, joined: true, splitWords: true, className: "alpha-router-logo--gradient" }) }), _jsx("p", { className: "login-brand__tagline login-brand__tagline--reveal", children: _jsx("span", { className: "login-brand__tagline-text", children: LOGIN_TAGLINE }) })] }), _jsx("div", { className: "login-highlights", children: LOGIN_HIGHLIGHTS.map((f, i) => (_jsxs("article", { className: "login-highlight login-highlight--reveal", style: { animationDelay: `${0.95 + i * 0.08}s` }, children: [_jsx("div", { className: "login-highlight__visual", children: f.art }), _jsxs("div", { className: "login-highlight__copy", children: [_jsx("h2", { children: f.title }), _jsx("p", { children: f.desc })] })] }, f.title))) })] }), _jsx("section", { className: "login-signin", "aria-label": "Sign in", children: _jsxs("div", { className: "login-panel", children: [_jsx("div", { className: "login-panel__shine", "aria-hidden": true }), _jsx("p", { className: "login-panel__eyebrow", children: "Welcome back" }), _jsx("h2", { className: "login-panel__title", children: pendingToken ? "Two-factor authentication" : "Sign in" }), _jsxs("form", { className: `login-form${shakeFields ? " login-form--shake" : ""}`, onSubmit: onSubmit, onAnimationEnd: (e) => {
                                        if (e.target === e.currentTarget)
                                            setShakeFields(false);
                                    }, children: [!pendingToken ? (_jsxs(_Fragment, { children: [_jsx("label", { className: "login-form__label", htmlFor: "login-username", children: "Username" }), _jsx("input", { id: "login-username", value: username, onChange: (e) => setUsername(e.target.value), autoComplete: "username", className: "login-form__input", placeholder: "your.username", "aria-invalid": shakeFields || !!error }), _jsx("label", { className: "login-form__label", htmlFor: "login-password", children: "Password" }), _jsx("input", { id: "login-password", type: "password", value: password, onChange: (e) => setPassword(e.target.value), autoComplete: "current-password", className: "login-form__input", placeholder: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022", "aria-invalid": shakeFields || !!error })] })) : (_jsxs(_Fragment, { children: [_jsx("p", { className: "login-panel__hint", children: "Enter the code from your authenticator app or a backup code." }), _jsx("label", { className: "login-form__label", htmlFor: "login-totp", children: "Authentication code" }), _jsx("input", { id: "login-totp", value: totpCode, onChange: (e) => setTotpCode(e.target.value), autoComplete: "one-time-code", inputMode: "numeric", className: "login-form__input", placeholder: "123456", autoFocus: true, "aria-invalid": shakeFields || !!error }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => {
                                                        setPendingToken(null);
                                                        setTotpCode("");
                                                        setError("");
                                                        setShakeFields(false);
                                                    }, children: "Back" })] })), error && _jsx("p", { className: "login-form__error", children: error }), _jsx("button", { className: "btn login-form__submit", type: "submit", children: pendingToken ? "Verify" : "Continue" })] }), (methods.saml || methods.oidc || methods.ldap) && (_jsxs("div", { className: "login-panel__footer", children: [methods.saml && (_jsx("a", { className: "login-panel__sso", href: "/api/auth/saml/login", children: "Sign in with SAML" })), methods.oidc && (_jsx("a", { className: "login-panel__sso", href: "/api/auth/oidc/login", children: "Sign in with OIDC" })), methods.ldap && _jsx("p", { className: "login-panel__hint", children: "LDAP: use your directory credentials." })] }))] }) })] }), _jsxs("p", { className: "login-page__legal", children: [PRODUCT_NAME_MARKED, " is a trademark of ", TRADEMARK_OWNER, "."] })] }));
}
