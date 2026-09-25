import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { getClient } from "../lib/client";
import { loadConfig } from "../lib/config";
import { cancelConnect, disconnect, hasPendingConnect, startConnect } from "../lib/connect";
import { broadcast, fromOwnPages, isExtensionMessage } from "../lib/messages";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import Chat from "./Chat";
import ConnectView from "./ConnectView";
import type { Me } from "./types";

type View =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "disconnected"; server: string; waiting: boolean; message: string }
  | { kind: "unreachable"; message: string }
  | { kind: "connected"; server: string; me: Me };

/** Where the panel stands: read from config.json, the stored tokens and /api/extension/me. */
async function currentView(): Promise<View> {
  const config = await loadConfig();
  if (!config.serverUrl) return { kind: "unconfigured" };
  const { tokens, api } = getClient();
  if (!(await tokens.isConnected())) {
    return { kind: "disconnected", server: config.serverUrl, waiting: await hasPendingConnect(), message: "" };
  }
  try {
    return { kind: "connected", server: config.serverUrl, me: await api.json<Me>("/api/extension/me") };
  } catch (err) {
    if (err instanceof DisconnectedError) {
      return { kind: "disconnected", server: config.serverUrl, waiting: false, message: err.message };
    }
    if (err instanceof TemporaryError) return { kind: "unreachable", message: err.message };
    return { kind: "unreachable", message: err instanceof ApiError ? err.message : "Something went wrong." };
  }
}

export default function App() {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [checks, setChecks] = useState(0);

  useEffect(() => {
    let active = true;
    currentView().then((next) => {
      if (active) setView(next);
    });
    return () => {
      active = false;
    };
  }, [checks]);

  useEffect(() => {
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      if (fromOwnPages(sender) && isExtensionMessage(message) && message.type === "auth-changed") {
        setChecks((n) => n + 1);
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  async function connect(server: string) {
    const url = await startConnect(server);
    await chrome.tabs.create({ url });
    setView({ kind: "disconnected", server, waiting: true, message: "" });
  }

  async function cancel() {
    await cancelConnect();
    setChecks((n) => n + 1);
  }

  async function signOut() {
    const { tokens, api } = getClient();
    try {
      await disconnect(tokens, (signal) => api.request("/api/extension/revoke", { method: "POST", signal }));
    } finally {
      // The panel looks again whatever happened: it says what it finds.
      await broadcast({ type: "auth-changed" }).catch(() => undefined);
      setChecks((n) => n + 1);
    }
  }

  if (view.kind === "loading") return <main className="panel panel__center" aria-busy="true" />;

  if (view.kind === "unconfigured") {
    return (
      <main className="panel panel__center">
        <h1 className="panel__title">Alpharouter</h1>
        <p className="panel__text">
          This copy of the extension belongs to no Alpharouter server. Download it from your Alpharouter: Settings →
          Extension.
        </p>
      </main>
    );
  }

  if (view.kind === "disconnected") {
    return (
      <ConnectView
        serverUrl={view.server}
        waiting={view.waiting}
        message={view.message}
        onConnect={() => void connect(view.server)}
        onCancel={() => void cancel()}
      />
    );
  }

  if (view.kind === "unreachable") {
    return (
      <main className="panel panel__center">
        <h1 className="panel__title">Alpharouter</h1>
        <p className="banner banner--error" role="alert">
          {view.message}
        </p>
        <div className="panel__actions">
          <button type="button" className="btn" onClick={() => setChecks((n) => n + 1)}>
            Try again
          </button>
        </div>
      </main>
    );
  }

  return (
    <Chat
      me={view.me}
      server={view.server}
      onDisconnect={() => void signOut()}
      onDisconnected={() => setChecks((n) => n + 1)}
    />
  );
}
