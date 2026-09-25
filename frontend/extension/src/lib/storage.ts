/**
 * Where the tokens live in a real browser (lib/tokens.ts says why each place).
 * A refresh still waiting for its answer keeps its attempt beside the refresh
 * token it spends.
 */

import type { Lock, PendingAttempt, StoredAccess, TokenStorage } from "./tokens";

const ACCESS_KEY = "alpharouter.access";
const DB_NAME = "alpharouter";
const STORE = "kv";
const REFRESH_KEY = "refresh";
const ATTEMPT_KEY = "refresh-attempt";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = run(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export const browserTokenStorage: TokenStorage = {
  async getAccess() {
    const value = (await chrome.storage.session.get(ACCESS_KEY))[ACCESS_KEY] as StoredAccess | undefined;
    return value && typeof value.token === "string" ? value : null;
  },
  async setAccess(value) {
    if (value) await chrome.storage.session.set({ [ACCESS_KEY]: value });
    else await chrome.storage.session.remove(ACCESS_KEY);
  },
  async getRefresh() {
    const value = await withStore<unknown>("readonly", (store) => store.get(REFRESH_KEY));
    return typeof value === "string" && value ? value : null;
  },
  async setRefresh(value) {
    if (value) await withStore("readwrite", (store) => store.put(value, REFRESH_KEY));
    else await withStore("readwrite", (store) => store.delete(REFRESH_KEY));
  },
  async getAttempt() {
    const value = await withStore<unknown>("readonly", (store) => store.get(ATTEMPT_KEY));
    const kept = value as Partial<PendingAttempt> | null | undefined;
    return kept && typeof kept.refresh === "string" && typeof kept.attempt === "string"
      ? { refresh: kept.refresh, attempt: kept.attempt }
      : null;
  },
  async setAttempt(value) {
    if (value) await withStore("readwrite", (store) => store.put(value, ATTEMPT_KEY));
    else await withStore("readwrite", (store) => store.delete(ATTEMPT_KEY));
  },
};

/** One refresh at a time across the panel, connected.html and anything else of ours. */
export const tokenLock: Lock = <T>(fn: () => Promise<T>) =>
  // The DOM typings wrap the callback's promise once more; the lock resolves with its value.
  navigator.locks.request("alpharouter-token", fn) as unknown as Promise<T>;
