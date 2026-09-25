import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, bootstrapSession, formatApiError, type SessionInfo } from "../api";
import { forgetAfterLogin, rememberAfterLogin } from "../lib/afterLogin";
import { PRODUCT_NAME } from "../lib/brand";
import { applyThemeToDocument } from "../lib/themeCache";

/**
 * Connect the browser extension: the page the extension's side panel opens.
 *
 * The extension sends its PKCE challenge, a state and its own connected.html
 * here. A signed-in user says yes or no; the server answers with the address
 * to go back to - connected.html with a one-time code, or with the refusal -
 * and the tab goes there. A signed-out user signs in first and comes back
 * (lib/afterLogin.ts).
 */

export type ConnectRequest = {
  redirectUri: string;
  extensionId: string;
  codeChallenge: string;
  state: string;
};

const REDIRECT_RE = /^(?:chrome-extension|extension):\/\/([a-p]{32})\/connected\.html$/;
const CHALLENGE_RE = /^[A-Za-z0-9_-]{43}$/;
const STATE_RE = /^[A-Za-z0-9_-]{16,128}$/;

export function parseConnectRequest(search: string): ConnectRequest | null {
  const params = new URLSearchParams(search);
  const redirectUri = params.get("redirect_uri") ?? "";
  const codeChallenge = params.get("code_challenge") ?? "";
  const state = params.get("state") ?? "";
  const match = REDIRECT_RE.exec(redirectUri);
  if (!match || params.get("code_challenge_method") !== "S256") return null;
  if (!CHALLENGE_RE.test(codeChallenge) || !STATE_RE.test(state)) return null;
  return { redirectUri, extensionId: match[1], codeChallenge, state };
}

/** Where the tab goes next; a seam for tests, which cannot leave the page. */
export const navigation = {
  go(url: string) {
    window.location.assign(url);
  },
};

type ExtensionInfo = { permitted: boolean; extension_id: string | null };

type View =
  | { kind: "checking" }
  | { kind: "invalid" }
  | { kind: "refused"; message: string }
  | { kind: "consent"; session: SessionInfo; error?: string }
  | { kind: "leaving"; denied: boolean };

const NOT_PERMITTED = "The browser extension is not enabled for your account. Ask your administrator to turn it on.";
const OTHER_SERVER =
  "This request comes from a copy of the extension that belongs to another server. Download the extension from this server: Settings → Extension.";

export default function ExtensionConnect() {
  const location = useLocation();
  const nav = useNavigate();
  const request = useMemo(() => parseConnectRequest(location.search), [location.search]);
  const [state, setView] = useState<View>({ kind: "checking" });
  const [busy, setBusy] = useState(false);
  const view: View = request ? state : { kind: "invalid" };

  useEffect(() => {
    document.title = `Connect the browser extension | ${PRODUCT_NAME}`;
    applyThemeToDocument();
    document.body.classList.add("login-route");
    return () => document.body.classList.remove("login-route");
  }, []);

  useEffect(() => {
    if (!request) return;
    let active = true;
    // Before anything that could send the tab to /login.
    rememberAfterLogin(location.pathname + location.search);
    (async () => {
      let session: SessionInfo;
      try {
        session = await bootstrapSession();
      } catch {
        if (active) nav("/login", { replace: true });
        return;
      }
      forgetAfterLogin();
      if (session.is_active === false) {
        if (active) setView({ kind: "refused", message: "Your account is disabled, so it cannot connect a browser." });
        return;
      }
      let info: ExtensionInfo | null = null;
      try {
        info = await api<ExtensionInfo>("/api/extension/info");
      } catch {
        info = null; // The server decides again when the user answers.
      }
      if (!active) return;
      if (info && !info.permitted) setView({ kind: "refused", message: NOT_PERMITTED });
      else if (info?.extension_id && info.extension_id !== request.extensionId) setView({ kind: "refused", message: OTHER_SERVER });
      else setView({ kind: "consent", session });
    })();
    return () => {
      active = false;
    };
  }, [request, location.pathname, location.search, nav]);

  async function answer(session: SessionInfo, deny: boolean) {
    if (!request || busy) return;
    setBusy(true);
    try {
      const result = await api<{ redirect_to: string }>("/api/extension/authorize", {
        method: "POST",
        body: JSON.stringify({
          redirect_uri: request.redirectUri,
          code_challenge: request.codeChallenge,
          code_challenge_method: "S256",
          state: request.state,
          deny,
        }),
      });
      // Only ever back to the extension's own page; the server checked it too.
      if (!result.redirect_to.startsWith(`${request.redirectUri}?`)) throw new Error("The server answered with an unexpected address.");
      setView({ kind: "leaving", denied: deny });
      navigation.go(result.redirect_to);
    } catch (err) {
      setView({ kind: "consent", session, error: formatApiError(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page extension-connect">
      <div className="login-page__mesh" aria-hidden />
      <div className="extension-connect__shell">
        <section className="login-panel extension-connect__panel" aria-labelledby="extension-connect-title">
          <p className="login-panel__eyebrow">Browser extension</p>
          {view.kind === "checking" && (
            <h1 className="login-panel__title" id="extension-connect-title">
              Checking…
            </h1>
          )}
          {view.kind === "invalid" && (
            <>
              <h1 className="login-panel__title" id="extension-connect-title">
                This link cannot connect a browser
              </h1>
              <p className="form-error" role="alert">
                It is incomplete or was changed. Open the {PRODUCT_NAME} extension&apos;s side panel and choose Connect again.
              </p>
            </>
          )}
          {view.kind === "refused" && (
            <>
              <h1 className="login-panel__title" id="extension-connect-title">
                This browser cannot be connected
              </h1>
              <p className="form-error" role="alert">
                {view.message}
              </p>
            </>
          )}
          {view.kind === "consent" && (
            <>
              <h1 className="login-panel__title" id="extension-connect-title">
                Connect this browser?
              </h1>
              <p className="extension-connect__lead">
                The {PRODUCT_NAME} extension in this browser asks to work for{" "}
                <strong>{view.session.display_name || view.session.username}</strong>. Once connected, it can:
              </p>
              <ul className="extension-connect__list">
                <li>chat with the models you can use here, saving chats to your history unless you choose Private;</li>
                <li>read a page only when you share it, within your organization&apos;s site rules;</li>
                <li>stay connected until you disconnect it or sign out of {PRODUCT_NAME}.</li>
              </ul>
              {view.error && (
                <p className="form-error" role="alert">
                  {view.error}
                </p>
              )}
              <div className="extension-connect__actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  aria-busy={busy}
                  onClick={() => void answer(view.session, false)}
                >
                  Connect
                </button>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void answer(view.session, true)}>
                  Cancel
                </button>
              </div>
              <p className="extension-connect__note">
                You can see and disconnect your browsers at any time in Settings → Extension.
              </p>
            </>
          )}
          {view.kind === "leaving" && (
            <h1 className="login-panel__title" id="extension-connect-title">
              {view.denied ? "Cancelled - returning to the extension…" : "Allowed - returning to the extension…"}
            </h1>
          )}
        </section>
      </div>
    </div>
  );
}
