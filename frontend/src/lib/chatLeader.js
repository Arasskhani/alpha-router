/** Multi-tab leader election: leader tab syncs chat folders; all tabs may sync sessions/messages. */
export const CHAT_SYNC_CHANNEL_NAME = "alpha_router_chat_sync";
export const CHAT_LEADER_LOCK_NAME = "alpha_router_chat_leader";
export const CHAT_REFRESH_EVENT_NAME = "alpha_router_chat_refresh";
const tabId = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `tab-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
let leader = false;
let channel = null;
const listeners = new Set();
function notify() {
    for (const fn of listeners)
        fn(leader);
}
function supportsLocks() {
    return typeof navigator !== "undefined" && "locks" in navigator;
}
function supportsBroadcast() {
    return typeof BroadcastChannel !== "undefined";
}
function holdLeaderLock() {
    if (!supportsLocks()) {
        leader = true;
        notify();
        return;
    }
    void navigator.locks
        .request(CHAT_LEADER_LOCK_NAME, { ifAvailable: true }, (lock) => {
        if (!lock) {
            leader = false;
            notify();
            return;
        }
        leader = true;
        notify();
        channel?.postMessage({ type: "leader", tabId });
        // Hold until the tab closes — never resolve (do NOT use steal: it demotes this tab).
        return new Promise(() => { });
    })
        .catch(() => {
        leader = true;
        notify();
    });
}
export function initChatLeader() {
    if (typeof window === "undefined")
        return;
    if (supportsBroadcast()) {
        channel = new BroadcastChannel(CHAT_SYNC_CHANNEL_NAME);
        channel.onmessage = (ev) => {
            const data = ev.data;
            if (data?.type === "leader" && data.tabId !== tabId) {
                leader = false;
                notify();
            }
            if (data?.type === "refresh") {
                window.dispatchEvent(new CustomEvent(CHAT_REFRESH_EVENT_NAME, { detail: data }));
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
export function isChatLeader() {
    return leader;
}
export function onChatLeaderChange(fn) {
    listeners.add(fn);
    fn(leader);
    return () => listeners.delete(fn);
}
export function broadcastChatRefresh(detail) {
    channel?.postMessage({ type: "refresh", ...detail });
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(CHAT_REFRESH_EVENT_NAME, { detail: { type: "refresh", ...detail } }));
    }
}
