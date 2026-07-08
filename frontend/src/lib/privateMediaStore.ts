/** IndexedDB blob storage for Private Mode chat media (images / attachments). */

export const PRIVATE_BLOB_REF_PREFIX = "private-blob://";

const DB_NAME = "nitro_private_media";
const DB_VERSION = 1;
const STORE_NAME = "blobs";

const blobUrlToRef = new Map<string, string>();

export class PrivateChatStorageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PrivateChatStorageError";
  }
}

export function isPrivateBlobRef(url: string): boolean {
  return url.startsWith(PRIVATE_BLOB_REF_PREFIX);
}

export function privateBlobRefId(ref: string): string {
  return ref.slice(PRIVATE_BLOB_REF_PREFIX.length);
}

export function refForHydratedBlobUrl(blobUrl: string): string | undefined {
  return blobUrlToRef.get(blobUrl);
}

function newBlobId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `blob-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onerror = () => reject(req.error ?? new Error("Could not open private media storage."));
    req.onsuccess = () => resolve(req.result);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
  });
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [meta, b64] = dataUrl.split(",", 2);
  if (!b64) throw new Error("Invalid data URL.");
  const mime = meta.match(/^data:(.*?);base64$/)?.[1] || "application/octet-stream";
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read private media blob."));
    reader.readAsDataURL(blob);
  });
}

async function readBlob(id: string): Promise<Blob | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(id);
    req.onerror = () => reject(req.error ?? new Error("Could not read private media."));
    req.onsuccess = () => resolve((req.result as Blob | undefined) ?? null);
    tx.oncomplete = () => db.close();
    tx.onerror = () => {
      db.close();
      reject(tx.error ?? new Error("Could not read private media."));
    };
  });
}

/** Store a data URL or Blob; returns a stable `private-blob://` ref for localStorage JSON. */
export async function storePrivateBlob(dataUrlOrBlob: string | Blob): Promise<string> {
  const blob =
    typeof dataUrlOrBlob === "string" ? dataUrlToBlob(dataUrlOrBlob) : dataUrlOrBlob;
  const id = newBlobId();
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(blob, id);
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error ?? new Error("Could not store private media."));
    };
  });
  return `${PRIVATE_BLOB_REF_PREFIX}${id}`;
}

/** Resolve a private blob ref to a `blob:` URL for display (revoke when done). */
export async function resolvePrivateBlobRef(ref: string): Promise<string> {
  if (!isPrivateBlobRef(ref)) return ref;
  const id = privateBlobRefId(ref);
  const blob = await readBlob(id);
  if (!blob) throw new Error("Private media not found in this browser.");
  const blobUrl = URL.createObjectURL(blob);
  blobUrlToRef.set(blobUrl, ref);
  return blobUrl;
}

export async function deletePrivateBlob(id: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error ?? new Error("Could not delete private media."));
    };
  });
}

/** Persist an in-memory media URL (data:, blob:, or existing ref) as a private blob ref. */
export async function storePrivateMediaUrl(url: string): Promise<string> {
  const trimmed = url.trim();
  if (!trimmed) return trimmed;
  if (isPrivateBlobRef(trimmed)) return trimmed;
  const existingRef = refForHydratedBlobUrl(trimmed);
  if (existingRef) return existingRef;
  if (trimmed.startsWith("data:")) return storePrivateBlob(trimmed);
  if (trimmed.startsWith("blob:")) {
    const blob = await fetch(trimmed).then((r) => r.blob());
    return storePrivateBlob(blob);
  }
  return trimmed;
}

/** Resolve private refs / blob URLs to a data URL suitable for upstream APIs. */
export async function resolvePrivateMediaUrlForApi(url: string): Promise<string> {
  const trimmed = url.trim();
  if (!trimmed) return trimmed;
  if (trimmed.startsWith("data:") || trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    return trimmed;
  }
  if (isPrivateBlobRef(trimmed)) {
    const blob = await readBlob(privateBlobRefId(trimmed));
    if (!blob) throw new Error("Private media not found in this browser.");
    return blobToDataUrl(blob);
  }
  if (trimmed.startsWith("blob:")) {
    const blob = await fetch(trimmed).then((r) => r.blob());
    return blobToDataUrl(blob);
  }
  return trimmed;
}

export function isQuotaExceededError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const name = (err as { name?: string }).name;
  if (name === "QuotaExceededError") return true;
  const code = (err as { code?: number }).code;
  return code === 22 || code === 1014;
}
