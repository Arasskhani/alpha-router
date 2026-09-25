import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { getClient } from "../lib/client";
import { loadConfig } from "../lib/config";
import { cancelConnect, disconnect, hasPendingConnect, startConnect } from "../lib/connect";
import { broadcast, fromOwnPages, isExtensionMessage } from "../lib/messages";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import AgentView from "./AgentView";
import Chat from "./Chat";
import ConnectView from "./ConnectView";
import type { Me } from "./types";

/** How long the panel waits for /api/extension/me before it offers to try again. */
const ME_TIMEOUT_MS = 15_000;

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
    // A request that hangs would leave the panel blank: past the wait it is
    // treated as the network trouble it is (TemporaryError).
    const me = await api.json<Me>("/api/extension/me", { signal: AbortSignal.timeout(ME_TIMEOUT_MS) });
    return { kind: "connected", server: config.serverUrl, me };
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
  /** Chat, or the browser agent when the account may use it. */
  const [tab, setTab] = useState<"chat" | "agent">("chat");

  useEffect(() => {
    let active = true;
    currentView()
      // Storage the panel cannot read, say: it offers to try again rather than staying blank.
      .catch((): View => ({ kind: "unreachable", message: "Something went wrong." }))
      .then((next) => {
        if (active) setView(next);
      });
    return () => {
      active = false;
    };
  }, [checks]);

  useEffect(() => {
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      if (!fromOwnPages(sender) || !isExtensionMessage(message)) return;
      if (message.type === "auth-changed") setChecks((n) => n + 1);
      // A right-click action or the shortcut is a question for the chat.
      if (message.type === "pending-action") setTab("chat");
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

  const chat = (
    <Chat
      me={view.me}
      server={view.server}
      onDisconnect={() => void signOut()}
      onDisconnected={() => setChecks((n) => n + 1)}
    />
  );
  if (!(view.me.features.chat && view.me.features.agent)) return chat;
  // Both stay mounted: a run goes on while the chat is shown, and the chat keeps its place.
  return (
    <div className="shell">
      <div className="shell__tabs" role="tablist" aria-label="Alpharouter">
        {(["chat", "agent"] as const).map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={`shell__tab${tab === name ? " shell__tab--on" : ""}`}
            onClick={() => setTab(name)}
          >
            {name === "chat" ? "Chat" : "Agent"}
          </button>
        ))}
      </div>
      <div className="shell__view" hidden={tab !== "chat"}>
        {chat}
      </div>
      <AgentView me={view.me} hidden={tab !== "agent"} onDisconnected={() => setChecks((n) => n + 1)} />
    </div>
  );
}
