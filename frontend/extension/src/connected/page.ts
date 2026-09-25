/**
 * connected.html: where the consent page sends the tab back with a code (or a
 * refusal). It finishes the connection, tells the side panel, and closes.
 */

import { finishConnect, type ConnectResult, type FinishDeps } from "../lib/connect";
import { broadcast } from "../lib/messages";

const CLOSE_AFTER_MS = 1500;

type Deps = FinishDeps & {
  closeTab: () => void;
  setTimeout: (fn: () => void, ms: number) => void;
};

function words(result: ConnectResult): { title: string; text: string } {
  if (result.kind === "connected") return { title: "Connected", text: "This browser is connected to Alpharouter. You can close this tab." };
  if (result.kind === "denied") return { title: "Not connected", text: "You chose not to connect this browser. You can close this tab." };
  return { title: "Not connected", text: result.message };
}

function show(doc: Document, title: string, text: string): void {
  const root = doc.getElementById("root");
  if (!root) return;
  root.replaceChildren();
  const heading = doc.createElement("h1");
  heading.textContent = title;
  const paragraph = doc.createElement("p");
  paragraph.textContent = text;
  paragraph.setAttribute("role", "status");
  root.append(heading, paragraph);
}

export async function runConnectedPage(doc: Document, location: Location, history: History, deps: Deps): Promise<ConnectResult> {
  show(doc, "Connecting…", "Finishing the connection to Alpharouter.");
  const search = location.search;
  // The code is spent either way: take it out of the address bar and history.
  history.replaceState(null, "", location.pathname);
  let result: ConnectResult;
  try {
    result = await finishConnect(search, deps);
  } catch {
    result = { kind: "failed", message: "The connection could not be finished. Start again from the extension's side panel." };
  }
  const { title, text } = words(result);
  show(doc, title, text);
  // The panel looks again whatever the answer: a failed attempt is over too,
  // and it would otherwise go on waiting for it.
  await broadcast({ type: "auth-changed" }).catch(() => undefined);
  if (result.kind !== "failed") deps.setTimeout(deps.closeTab, CLOSE_AFTER_MS);
  return result;
}
