/**
 * A chrome.debugger session for one tab: the transport under full control.
 *
 * chrome.debugger is callback-based and reports failures through
 * chrome.runtime.lastError, so every call is wrapped in a promise that rejects
 * with a real Error. The session:
 *
 * - attaches to a tab and sends CDP commands;
 * - buffers the data from an intercepted native drag (Input.dragIntercepted);
 * - hands a JavaScript dialog (Page.javascriptDialogOpening) to its owner as
 *   it opens: the page - and the input command that opened it - wait until
 *   it is answered, so it must be answered from the event, not after;
 * - notices when the session ends for any reason (the run finishing, the panel
 *   closing, or the user pressing Cancel on Chrome's "started debugging" bar,
 *   which arrives as onDetach) and tells its owner through onDetached, once.
 *
 * While attached Chrome shows its debugging bar; the session is attached only
 * for the length of a run, and detach() is safe to call more than once.
 */

const CDP_VERSION = "1.3";

/** How long a command may take before the session gives up on it; longer for a capture. Not while a dialog holds the page. */
const SEND_TIMEOUT_MS = 10_000;
export const CAPTURE_TIMEOUT_MS = 15_000;

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
  private dialogOpen = false;
  private onDialogCb: ((dialog: DialogInfo) => void) | null = null;
  private onDetachedCb: ((reason: DetachReason) => void) | null = null;
  private readonly onEvent: (source: chrome.debugger.Debuggee, method: string, params?: object) => void;
  private readonly onDetach: (source: chrome.debugger.Debuggee, reason: string) => void;

  constructor(tabId: number, api: DebuggerApi = chrome.debugger) {
    this.tabId = tabId;
    this.api = api;
    this.onEvent = (source, method, params) => {
      if (source.tabId !== this.tabId) return;
      if (method === "Input.dragIntercepted") this.drag = (params as { data?: DragData })?.data ?? {};
      else if (method === "Page.javascriptDialogOpening") {
        this.dialogOpen = true;
        this.onDialogCb?.(params as DialogInfo);
      } else if (method === "Page.javascriptDialogClosed") this.dialogOpen = false;
    };
    this.onDetach = (source, reason) => {
      if (source.tabId !== this.tabId) return;
      this.attached = false;
      this.detachedReason = reason || "target_closed";
      // An ended session hears nothing more: a new session of the same tab gets the tab's events from now on,
      // and a dialog there must not be answered twice (or by a run that is over).
      this.api.onEvent.removeListener(this.onEvent);
      this.api.onDetach.removeListener(this.onDetach);
      this.onDialogCb = null;
      this.dialogOpen = false;
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

  /**
   * Send a command; it fails after `timeoutMs` without an answer. While a
   * dialog holds the page, the input that opened it is waiting on the user,
   * not stuck, so the wait goes on until the dialog is answered.
   */
  async send<T = unknown>(method: string, params: Record<string, unknown> = {}, timeoutMs: number = SEND_TIMEOUT_MS): Promise<T> {
    if (!this.attached) throw new Error(`${method}: not attached`);
    return await new Promise<T>((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout>;
      const arm = () => {
        timer = setTimeout(() => {
          if (settled) return;
          if (this.dialogOpen) {
            arm();
            return;
          }
          settled = true;
          reject(new Error(`${method}: the browser did not answer within ${Math.round(timeoutMs / 1000)} s`));
        }, timeoutMs);
      };
      arm();
      this.api.sendCommand(this.target, method, params, (result) => {
        const err = lastError();
        if (settled) return;
        settled = true;
        clearTimeout(timer);
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

  /** Who answers the page's JavaScript dialogs, called as each one opens (null: nobody). */
  onDialog(cb: ((dialog: DialogInfo) => void) | null): void {
    this.onDialogCb = cb;
  }

  /** Whether a JavaScript dialog is open on the page now. */
  get hasDialog(): boolean {
    return this.dialogOpen;
  }

  /** Answer a JavaScript dialog the page opened (accept or dismiss, with optional prompt text). */
  async handleDialog(accept: boolean, promptText?: string): Promise<void> {
    await this.send("Page.handleJavaScriptDialog", promptText === undefined ? { accept } : { accept, promptText });
    this.dialogOpen = false;
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
