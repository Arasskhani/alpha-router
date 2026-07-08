/** Multi-tab leader election: leader tab syncs chat folders; all tabs may sync sessions/messages. */

const CHANNEL_NAME = "nitro-chat-sync";
const LOCK_NAME = "nitro-chat-leader";

const tabId =
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `tab-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

let leader = false;
let channel: BroadcastChannel | null = null;
const listeners = new Set<(isLeader: boolean) => void>();

function notify() {
  for (const fn of listeners) fn(leader);
}

function supportsLocks(): boolean {
  return typeof navigator !== "undefined" && "locks" in navigator;
}

function supportsBroadcast(): boolean {
  return typeof BroadcastChannel !== "undefined";
}

function holdLeaderLock(): void {
  if (!supportsLocks()) {
    leader = true;
    notify();
    return;
  }
  void navigator.locks
    .request(
      LOCK_NAME,
      { ifAvailable: true },
      (lock) => {
        if (!lock) {
          leader = false;
          notify();
          return;
        }
        leader = true;
        notify();
        channel?.postMessage({ type: "leader", tabId });
        // Hold until the tab closes — never resolve (do NOT use steal: it demotes this tab).
        return new Promise<void>(() => {});
      },
    )
    .catch(() => {
      leader = true;
      notify();
    });
}

export function initChatLeader(): void {
  if (typeof window === "undefined") return;
  if (supportsBroadcast()) {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (ev) => {
      const data = ev.data as { type?: string; tabId?: string };
      if (data?.type === "leader" && data.tabId !== tabId) {
        leader = false;
        notify();
      }
      if (data?.type === "refresh") {
        window.dispatchEvent(new CustomEvent("nitro-chat-refresh", { detail: data }));
      }
    };
  }
  holdLeaderLock();
  // Retry when this tab becomes visible again (leader tab may have closed).
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !leader) {
      holdLeaderLock();
    }
  });
}

export function isChatLeader(): boolean {
  return leader;
}

export function onChatLeaderChange(fn: (isLeader: boolean) => void): () => void {
  listeners.add(fn);
  fn(leader);
  return () => listeners.delete(fn);
}

export function broadcastChatRefresh(detail?: Record<string, unknown>): void {
  channel?.postMessage({ type: "refresh", ...detail });
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("nitro-chat-refresh", { detail: { type: "refresh", ...detail } }));
  }
}
