import { useEffect } from "react";
import { api } from "../api";
import { PRESENCE_PING_INTERVAL_MS } from "../lib/presence";
import { getSessionUser } from "../lib/session";
/** Report this session as online while a tab is visible.
 *
 * Hidden tabs stop pinging deliberately: browsers throttle background timers,
 * and letting the server-side key expire is what turns a closed laptop into an
 * offline user. Failures are ignored — presence must never surface an error.
 */
export default function usePresenceHeartbeat() {
    useEffect(() => {
        if (!getSessionUser())
            return;
        let stopped = false;
        const ping = () => {
            if (stopped || document.visibilityState !== "visible")
                return;
            void api("/api/user/presence", { method: "POST" }).catch(() => { });
        };
        ping();
        const timer = window.setInterval(ping, PRESENCE_PING_INTERVAL_MS);
        document.addEventListener("visibilitychange", ping);
        return () => {
            stopped = true;
            window.clearInterval(timer);
            document.removeEventListener("visibilitychange", ping);
        };
    }, []);
}
