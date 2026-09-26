/**
 * A chrome.debugger session for one tab: the transport under full control.
 *
 * chrome.debugger is callback-based and reports failures through
 * chrome.runtime.lastError, so every call is wrapped in a promise that rejects
 * with a real Error. The session:
 *
 * - attaches to a tab and sends CDP commands;
 * - buffers the events full control needs - the data from an intercepted native
 *   drag (Input.dragIntercepted), and JavaScript dialogs (Page.javascriptDialogOpening);
 * - notices when the session ends for any reason (the run finishing, the panel
 *   closing, or the user pressing Cancel on Chrome's "started debugging" bar,
 *   which arrives as onDetach) and tells its owner through onDetached, once.
 *
 * While attached Chrome shows its debugging bar; the session is attached only
 * for the length of a run, and detach() is safe to call more than once.
 */

const CDP_VERSION = "1.3";

export type CdpTarget = { tabId: number };
export type DragData = Record<string, unknown>;
export type DialogInfo = { type: string; message: string; url?: string };
export type DetachReason = string;

type DebuggerApi = typeof chrome.debugger;

function lastError(): string | null {
  const err = chrome.runtime.lastError;
  return err ? err.message || "debugger error" : null;
}

export class CdpSession {
  readonly tabId: number;
  private readonly api: DebuggerApi;
  private attached = false;
  private detachedReason: DetachReason | null = null;
  private drag: DragData | null = null;
  private dialog: DialogInfo | null = null;
  private onDetachedCb: ((reason: DetachReason) => void) | null = null;
  private readonly onEvent: (source: chrome.debugger.Debuggee, method: string, params?: object) => void;
  private readonly onDetach: (source: chrome.debugger.Debuggee, reason: string) => void;

  constructor(tabId: number, api: DebuggerApi = chrome.debugger) {
    this.tabId = tabId;
    this.api = api;
    this.onEvent = (source, method, params) => {
      if (source.tabId !== this.tabId) return;
      if (method === "Input.dragIntercepted") this.drag = (params as { data?: DragData })?.data ?? {};
      else if (method === "Page.javascriptDialogOpening") this.dialog = params as DialogInfo;
    };
    this.onDetach = (source, reason) => {
      if (source.tabId !== this.tabId) return;
      this.attached = false;
      this.detachedReason = reason || "target_closed";
      this.onDetachedCb?.(this.detachedReason);
    };
  }

  get isAttached(): boolean {
    return this.attached;
  }

  /** Called once when the session ends for any reason; set before attaching. */
  onDetached(cb: (reason: DetachReason) => void): void {
    this.onDetachedCb = cb;
  }

  get target(): CdpTarget {
    return { tabId: this.tabId };
  }

  async attach(): Promise<void> {
    this.api.onEvent.addListener(this.onEvent);
    this.api.onDetach.addListener(this.onDetach);
    await new Promise<void>((resolve, reject) => {
      this.api.attach(this.target, CDP_VERSION, () => {
        const err = lastError();
        if (err) reject(new Error(`attach: ${err}`));
        else resolve();
      });
    });
    this.attached = true;
    this.detachedReason = null;
  }

  async send<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!this.attached) throw new Error(`${method}: not attached`);
    return await new Promise<T>((resolve, reject) => {
      this.api.sendCommand(this.target, method, params, (result) => {
        const err = lastError();
        if (err) reject(new Error(`${method}: ${err}`));
        else resolve(result as T);
      });
    });
  }

  /** The data of an intercepted native drag since the last call, or null. */
  async takeDragData(): Promise<DragData | null> {
    const data = this.drag;
    this.drag = null;
    return data;
  }

  /** A JavaScript dialog waiting on the page since the last call, or null. */
  takeDialog(): DialogInfo | null {
    const dialog = this.dialog;
    this.dialog = null;
    return dialog;
  }

  /** Answer a JavaScript dialog the page opened (accept or dismiss, with optional prompt text). */
  async handleDialog(accept: boolean, promptText?: string): Promise<void> {
    await this.send("Page.handleJavaScriptDialog", promptText === undefined ? { accept } : { accept, promptText });
  }

  async detach(): Promise<void> {
    this.api.onEvent.removeListener(this.onEvent);
    this.api.onDetach.removeListener(this.onDetach);
    if (!this.attached) return;
    this.attached = false;
    await new Promise<void>((resolve) => {
      this.api.detach(this.target, () => {
        lastError(); // a target that already went away is not an error worth raising on cleanup
        resolve();
      });
    });
  }
}
