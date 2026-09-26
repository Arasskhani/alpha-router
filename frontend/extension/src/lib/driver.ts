/**
 * Which driver a run uses, chosen per run and failing soft.
 *
 * Full control drives the page through chrome.debugger (the cdp driver). Chrome
 * can refuse the attach - an enterprise policy that sets runtime_blocked_hosts
 * for the extension (Chrome 155+), a screenshot or DLP rule, a DevTools
 * restriction - and full control may simply be off. In every one of those cases
 * the run falls back to the dom path (the existing content-script agent) rather
 * than failing, and the reason is reported so the panel can say which driver is
 * running and why.
 *
 * The dom fallback keeps its current implementation (ref-based actions and
 * captureVisibleTab); this only decides whether to attach the cdp driver. When
 * it returns the cdp driver it is already attached (start() ran); the caller
 * detaches it with stop() when the run ends.
 */

import { CdpSession } from "./cdp";
import { CdpDriver } from "./cdpDriver";

export type DriverChoice =
  | { mode: "cdp"; driver: CdpDriver }
  | { mode: "dom"; driver: null; reason: string };

export async function chooseDriver(
  tabId: number,
  options: { fullControl: boolean; maxSide: number },
): Promise<DriverChoice> {
  if (!options.fullControl) return { mode: "dom", driver: null, reason: "full control is off" };
  const driver = new CdpDriver(new CdpSession(tabId), { maxSide: options.maxSide });
  try {
    await driver.start();
    return { mode: "cdp", driver };
  } catch (error) {
    // Chrome refused the attach; leave nothing attached and use the dom path.
    await driver.stop().catch(() => undefined);
    const reason = error instanceof Error ? error.message : String(error);
    return { mode: "dom", driver: null, reason };
  }
}
