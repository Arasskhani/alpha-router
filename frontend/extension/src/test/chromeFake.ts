/**
 * An in-memory stand-in for the chrome.* APIs the extension uses, for tests.
 *
 * Only what the extension calls, behaving the way Chrome documents it:
 * storage areas with change events, runtime messages delivered to every
 * other listener, tabs, permissions and scripting calls recorded for the
 * test to inspect or answer.
 */

import { vi } from "vitest";

export const EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop";
/** The window the side panel belongs to. */
const CURRENT_WINDOW = 1;

type Listener = (...args: never[]) => unknown;

function event<T extends Listener>() {
  const listeners = new Set<T>();
  return {
    addListener: (fn: T) => void listeners.add(fn),
    removeListener: (fn: T) => void listeners.delete(fn),
    hasListener: (fn: T) => listeners.has(fn),
    emit: (...args: Parameters<T>) => [...listeners].map((fn) => fn(...args)),
    listeners,
  };
}

function storageArea(name: string, changed: ReturnType<typeof event>) {
  const data = new Map<string, unknown>();
  const clone = <V>(value: V): V => (value === undefined ? value : (JSON.parse(JSON.stringify(value)) as V));
  return {
    data,
    async get(keys?: string | string[] | null) {
      const wanted = keys == null ? [...data.keys()] : Array.isArray(keys) ? keys : [keys];
      const out: Record<string, unknown> = {};
      for (const key of wanted) if (data.has(key)) out[key] = clone(data.get(key));
      return out;
    },
    async set(items: Record<string, unknown>) {
      const changes: Record<string, { oldValue?: unknown; newValue?: unknown }> = {};
      for (const [key, value] of Object.entries(items)) {
        changes[key] = { oldValue: clone(data.get(key)), newValue: clone(value) };
        data.set(key, clone(value));
      }
      changed.emit(changes as never, name as never);
    },
    async remove(keys: string | string[]) {
      const changes: Record<string, { oldValue?: unknown }> = {};
      for (const key of Array.isArray(keys) ? keys : [keys]) {
        if (data.has(key)) changes[key] = { oldValue: data.get(key) };
        data.delete(key);
      }
      changed.emit(changes as never, name as never);
    },
    setAccessLevel: vi.fn(async () => undefined),
  };
}

export function installChromeFake(options: { version?: string } = {}) {
  const onMessage = event<(message: unknown, sender: chrome.runtime.MessageSender, respond: (r?: unknown) => void) => unknown>();
  const onChanged = event();
  const onInstalled = event();
  const onClicked = event();
  const onActivated = event<(info: { tabId: number; windowId: number }) => void>();
  const onUpdated = event<(tabId: number, change: Record<string, unknown>, tab: chrome.tabs.Tab) => void>();
  const onRemoved = event<(tabId: number, info: { windowId: number; isWindowClosing: boolean }) => void>();
  const onPermissionsAdded = event<(permissions: { origins?: string[] }) => void>();
  const onPermissionsRemoved = event<(permissions: { origins?: string[] }) => void>();
  const tabs = new Map<number, chrome.tabs.Tab>();
  let nextTab = 1;

  const fake = {
    runtime: {
      id: EXTENSION_ID,
      getURL: (path: string) => `chrome-extension://${EXTENSION_ID}/${path.replace(/^\//, "")}`,
      getManifest: () => ({ version: options.version ?? "1.0.0.1", manifest_version: 3 }),
      onMessage,
      onInstalled,
      /** Messages sent by the code under test; a page never receives its own. */
      sent: [] as unknown[],
      sendMessage: vi.fn(async (message: unknown) => {
        fake.runtime.sent.push(message);
      }),
      /** Deliver a message as if another page of the extension sent it. */
      deliver(message: unknown, sender: Partial<chrome.runtime.MessageSender> = {}) {
        return onMessage.emit(message, { id: EXTENSION_ID, url: `chrome-extension://${EXTENSION_ID}/other.html`, ...sender }, () => undefined);
      },
    },
    storage: {
      session: storageArea("session", onChanged),
      local: storageArea("local", onChanged),
      onChanged,
    },
    tabs: {
      created: [] as Array<{ url?: string; active?: boolean }>,
      create: vi.fn(async (props: { url?: string; active?: boolean }) => {
        fake.tabs.created.push(props);
        const tab = { id: nextTab++, url: props.url, active: true, windowId: CURRENT_WINDOW } as chrome.tabs.Tab;
        tabs.set(tab.id!, tab);
        return tab;
      }),
      get: vi.fn(async (id: number) => tabs.get(id)),
      query: vi.fn(async (info: { active?: boolean; currentWindow?: boolean } = {}) =>
        [...tabs.values()].filter(
          (tab) =>
            (info.active === undefined || tab.active === info.active) &&
            (!info.currentWindow || tab.windowId === CURRENT_WINDOW),
        ),
      ),
      remove: vi.fn(async (id: number) => {
        const tab = tabs.get(id);
        tabs.delete(id);
        if (tab) onRemoved.emit(id, { windowId: tab.windowId, isWindowClosing: false });
      }),
      getCurrent: vi.fn((callback?: (tab?: chrome.tabs.Tab) => void) => callback?.(undefined)),
      /** What Chrome captures of the visible tab: a tiny JPEG data URL. */
      captureVisibleTab: vi.fn(async (_windowId: number, _options?: unknown) => "data:image/jpeg;base64,/9j/4AAQSkZJRg=="),
      onActivated,
      onUpdated,
      onRemoved,
      /** Put a tab in place for the code under test to find. */
      add(tab: Partial<chrome.tabs.Tab>) {
        const full = { id: nextTab++, active: false, windowId: CURRENT_WINDOW, ...tab } as chrome.tabs.Tab;
        tabs.set(full.id!, full);
        return full;
      },
      /** The user switches to this tab. */
      activate(tabId: number) {
        const chosen = tabs.get(tabId)!;
        for (const tab of tabs.values()) if (tab.windowId === chosen.windowId) tab.active = tab.id === tabId;
        onActivated.emit({ tabId, windowId: chosen.windowId });
      },
      /** A tab loads another page, or its title changes. */
      update(tabId: number, change: { url?: string; title?: string }) {
        const tab = tabs.get(tabId)!;
        Object.assign(tab, change);
        onUpdated.emit(tabId, change, tab);
      },
    },
    permissions: {
      granted: new Set<string>(),
      /** What the user answers the next time Chrome asks. */
      answer: true,
      contains: vi.fn(async ({ origins = [] }: { origins?: string[] }) => origins.every((o) => fake.permissions.granted.has(o))),
      getAll: vi.fn(async () => ({ origins: [...fake.permissions.granted], permissions: [] as string[] })),
      request: vi.fn(async ({ origins = [] }: { origins?: string[] }) => {
        if (!fake.permissions.answer) return false;
        const added = origins.filter((origin) => !fake.permissions.granted.has(origin));
        for (const origin of added) fake.permissions.granted.add(origin);
        if (added.length) onPermissionsAdded.emit({ origins: added });
        return true;
      }),
      /** The user takes a site back (chrome://extensions, or the site-access menu). */
      revoke(origin: string) {
        fake.permissions.granted.delete(origin);
        onPermissionsRemoved.emit({ origins: [origin] });
      },
      onAdded: onPermissionsAdded,
      onRemoved: onPermissionsRemoved,
    },
    scripting: {
      executeScript: vi.fn(async (_injection: unknown) => [] as Array<{ result?: unknown }>),
    },
    sidePanel: {
      open: vi.fn(async () => undefined),
      setPanelBehavior: vi.fn(async () => undefined),
    },
    contextMenus: {
      create: vi.fn(),
      removeAll: vi.fn((callback?: () => void) => callback?.()),
      onClicked,
    },
    commands: { onCommand: event() },
    windows: {
      WINDOW_ID_CURRENT: -2,
      /** The window of the page asking: the side panel's. */
      getCurrent: vi.fn(async () => ({ id: CURRENT_WINDOW }) as chrome.windows.Window),
    },
  };
  vi.stubGlobal("chrome", fake);
  return fake;
}

export type ChromeFake = ReturnType<typeof installChromeFake>;
