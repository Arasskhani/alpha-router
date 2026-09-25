import { useEffect, useState } from "react";
import { api, formatApiError } from "../api";
import { useConfirm } from "../context/ConfirmContext";
import { copyTextToClipboard } from "../lib/clipboard";
import { formatLocalDateTime } from "../lib/dateTime";
import { PRODUCT_NAME } from "../lib/brand";

/**
 * Settings → Extension: download the browser extension, install it in Chrome
 * or Edge, and see and disconnect the browsers connected to this account.
 * The last section is what IT needs to install it with Group Policy instead.
 */

type ExtensionInfo = {
  available: boolean;
  permitted: boolean;
  reason: string | null;
  version: string | null;
  extension_id: string | null;
  update_url: string | null;
  gpo_value: string | null;
};

type ConnectedBrowser = {
  id: string;
  device_name: string;
  created_at: string | null;
  last_used_at: string | null;
  last_ip: string | null;
};

type Browser = "chrome" | "edge";

const EXTENSIONS_PAGE: Record<Browser, string> = { chrome: "chrome://extensions", edge: "edge://extensions" };
const DEVELOPER_MODE: Record<Browser, string> = {
  chrome: "Turn on Developer mode (top right).",
  edge: "Turn on Developer mode (in the left-hand menu).",
};

function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyTextToClipboard(value)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }
  return (
    <label className="settings-field personal-api-key-field">
      <span className="settings-label">{label}</span>
      <div className="personal-api-key-field__row">
        <input readOnly value={value} className="settings-row__control mono personal-api-key-field__input" aria-label={label} />
        <button
          type="button"
          className="btn btn-sm btn-ghost personal-api-key-field__copy"
          onClick={() => void copy()}
          aria-label={`Copy ${label}`}
          title={`Copy ${label}`}
        >
          {copied ? "✓" : "Copy"}
        </button>
      </div>
    </label>
  );
}

export default function ExtensionPanel() {
  const { confirm } = useConfirm();
  const [info, setInfo] = useState<ExtensionInfo | null>(null);
  const [infoError, setInfoError] = useState("");
  const [infoLoading, setInfoLoading] = useState(true);
  // null until loaded: "no browser is connected" is a claim, not a default.
  const [browsers, setBrowsers] = useState<ConnectedBrowser[] | null>(null);
  const [browsersError, setBrowsersError] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [browser, setBrowser] = useState<Browser>("chrome");
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let active = true;
    api<ExtensionInfo>("/api/extension/info")
      .then((row) => {
        if (active) setInfo(row);
      })
      .catch((err) => {
        if (active) setInfoError(formatApiError(err));
      })
      .finally(() => {
        if (active) setInfoLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Separately, and again after every Disconnect: one failing never blanks the other.
  useEffect(() => {
    let active = true;
    api<{ items: ConnectedBrowser[] }>("/api/extension/sessions")
      .then((rows) => {
        if (!active) return;
        setBrowsers(rows.items);
        setBrowsersError("");
      })
      .catch((err) => {
        if (active) setBrowsersError(formatApiError(err));
      });
    return () => {
      active = false;
    };
  }, [reloads]);

  async function disconnect(row: ConnectedBrowser) {
    const name = row.device_name || "this browser";
    const ok = await confirm({
      title: "Disconnect this browser?",
      message: `The ${PRODUCT_NAME} extension in ${name} stops working until someone connects it again from its side panel.`,
      confirmLabel: "Disconnect",
      danger: true,
    });
    if (!ok) return;
    setBusyId(row.id);
    setMessage("");
    setError("");
    try {
      await api(`/api/extension/sessions/${encodeURIComponent(row.id)}`, { method: "DELETE" });
      setMessage(`${name} was disconnected.`);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
      // Whatever happened - it may have been disconnected elsewhere already.
      setReloads((count) => count + 1);
    }
  }

  if (infoLoading) return <p className="muted">Loading extension settings…</p>;

  const canDownload = Boolean(info?.permitted && info.available);

  return (
    <div className="settings-section extension-panel">
      <h2>Browser extension</h2>
      <p className="settings-section-desc">
        Use {PRODUCT_NAME} in Chrome or Edge: chat in a side panel next to any page, and ask about the page you
        are on. Chats are saved to your history, as they are here.
      </p>

      {infoError && (
        <p className="settings-error" role="alert">
          Could not load the extension&apos;s details: {infoError}
        </p>
      )}
      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="settings-success" role="status">
          {message}
        </p>
      )}

      {info && !info.permitted && (
        <p className="docs-callout docs-callout-info" role="status">
          The browser extension is not enabled for your account. Ask your administrator if you need it.
        </p>
      )}
      {info?.permitted && !info.available && (
        <p className="docs-callout docs-callout-warn" role="status">
          The extension cannot be downloaded from this server right now. {info.reason}
        </p>
      )}

      {canDownload && info && (
        <div className="settings-list">
          <div className="settings-row-block settings-row-block--open">
            <div className="settings-row">
              <div className="settings-row__meta">
                <span className="settings-row__title">{PRODUCT_NAME} extension</span>
                <span className="settings-row__hint">Version {info.version} · for this server only</span>
              </div>
              <div className="settings-row__trail">
                <a className="btn btn-sm btn-primary" href="/api/extension/download" download>
                  Download
                </a>
              </div>
            </div>
            <div className="settings-row__detail extension-panel__install">
              <div className="theme-segment extension-panel__browsers" role="group" aria-label="Browser">
                {(["chrome", "edge"] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`theme-segment__btn${browser === item ? " is-active" : ""}`}
                    aria-pressed={browser === item}
                    onClick={() => setBrowser(item)}
                  >
                    {item === "chrome" ? "Chrome" : "Edge"}
                  </button>
                ))}
              </div>
              <ol className="extension-panel__steps">
                <li>Download the file and unzip it (right-click → Extract All). Keep the folder: the browser runs the extension from it.</li>
                <li>
                  Open <span className="mono">{EXTENSIONS_PAGE[browser]}</span> in a new tab.
                </li>
                <li>{DEVELOPER_MODE[browser]}</li>
                <li>Choose Load unpacked and select the unzipped folder.</li>
                <li>
                  Pin {PRODUCT_NAME} to the toolbar, open it, and choose Connect. You will be asked to allow it here.
                </li>
              </ol>
              <p className="settings-hint">
                To update, download again, unzip over the same folder, and press reload on the extension&apos;s card.
                The extension tells you when a new version is out.
              </p>
            </div>
          </div>
        </div>
      )}

      <h3 className="extension-panel__heading">Connected browsers</h3>
      {browsersError ? (
        <p className="settings-error" role="alert">
          Could not load your connected browsers: {browsersError}
        </p>
      ) : browsers === null ? (
        <p className="muted">Loading…</p>
      ) : browsers.length === 0 ? (
        <p className="settings-hint">No browser is connected.</p>
      ) : (
        <div className="settings-list">
          {browsers.map((row) => (
            <div className="settings-row-block" key={row.id}>
              <div className="settings-row">
                <div className="settings-row__meta">
                  <span className="settings-row__title">{row.device_name || "Browser"}</span>
                  <span className="settings-row__hint">
                    Connected {formatLocalDateTime(row.created_at)} · Last used {formatLocalDateTime(row.last_used_at)}
                    {row.last_ip ? <> · {row.last_ip}</> : null}
                  </span>
                </div>
                <div className="settings-row__trail">
                  <button
                    type="button"
                    className="settings-row__action settings-row__action--danger"
                    disabled={busyId !== null}
                    aria-label={`Disconnect ${row.device_name || "browser"}`}
                    onClick={() => void disconnect(row)}
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="settings-hint">
        Signing out of {PRODUCT_NAME} disconnects every browser too; connect again from the extension&apos;s side
        panel.
      </p>

      {info?.permitted && info.extension_id && info.update_url && info.gpo_value && (
        <details className="extension-panel__it">
          <summary>For IT: install it with Group Policy</summary>
          <p className="settings-hint">
            Add the value below to the ExtensionInstallForcelist policy (Chrome: Google Chrome → Extensions; Edge:
            Microsoft Edge → Extensions). Browsers then install the extension from this server and keep it up to
            date, with no Developer mode.
          </p>
          <CopyValue label="Extension ID" value={info.extension_id} />
          <CopyValue label="Update URL" value={info.update_url} />
          <CopyValue label="Policy value" value={info.gpo_value} />
        </details>
      )}
    </div>
  );
}
