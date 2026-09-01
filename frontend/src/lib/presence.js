/** Online-presence helpers for the admin Users table.
 *
 * Presence has no per-row indicator: the Online Users filter is the whole
 * feature. What remains here is the browser ping cadence and the detection of
 * an unavailable backend, kept out of React so both can be unit-tested.
 */
/** Browser ping cadence. Must stay well below PRESENCE_TTL_SECONDS (90s). */
export const PRESENCE_PING_INTERVAL_MS = 30_000;
/** How often the Users table refetches while the Online filter is active. */
export const PRESENCE_REFRESH_INTERVAL_MS = 20_000;
/** False when the server could not resolve presence for a non-empty list, in
 * which case the Online filter was ignored and the page has to say so. An empty
 * list carries no signal and is not treated as an outage. */
export function presenceAvailableFromUserRows(rows) {
    if (!rows.length)
        return true;
    return rows.some((row) => row.online === true || row.online === false);
}
