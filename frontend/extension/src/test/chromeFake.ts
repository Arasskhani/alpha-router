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
        const tab = { id: nextTab++, url: props.url, active: true } as chrome.tabs.Tab;
        tabs.set(tab.id!, tab);
        return tab;
      }),
      get: vi.fn(async (id: number) => tabs.get(id)),
      query: vi.fn(async () => [...tabs.values()]),
      remove: vi.fn(async (id: number) => void tabs.delete(id)),
      getCurrent: vi.fn((callback?: (tab?: chrome.tabs.Tab) => void) => callback?.(undefined)),
      onActivated: event(),
      onUpdated: event(),
      /** Put a tab in place for the code under test to find. */
      add(tab: Partial<chrome.tabs.Tab>) {
        const full = { id: nextTab++, active: false, windowId: 1, ...tab } as chrome.tabs.Tab;
        tabs.set(full.id!, full);
        return full;
      },
    },
    permissions: {
      granted: new Set<string>(),
      contains: vi.fn(async ({ origins = [] }: { origins?: string[] }) => origins.every((o) => fake.permissions.granted.has(o))),
      request: vi.fn(async ({ origins = [] }: { origins?: string[] }) => {
        for (const origin of origins) fake.permissions.granted.add(origin);
        return true;
      }),
    },
    scripting: {
      executeScript: vi.fn(async () => [] as Array<{ result?: unknown }>),
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
    windows: { WINDOW_ID_CURRENT: -2 },
  };
  vi.stubGlobal("chrome", fake);
  return fake;
}

export type ChromeFake = ReturnType<typeof installChromeFake>;
