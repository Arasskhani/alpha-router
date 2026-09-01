/** IndexedDB blob storage for Private Mode chat media (images / attachments). */
export const PRIVATE_BLOB_REF_PREFIX = "private-blob://";
export const PRIVATE_MEDIA_DB_NAME = "alpha_router_private_media";
const DB_VERSION = 1;
const STORE_NAME = "blobs";
const blobUrlToRef = new Map();
export class PrivateChatStorageError extends Error {
    constructor(message) {
        super(message);
        this.name = "PrivateChatStorageError";
    }
}
export function isPrivateBlobRef(url) {
    return url.startsWith(PRIVATE_BLOB_REF_PREFIX);
}
export function privateBlobRefId(ref) {
    return ref.slice(PRIVATE_BLOB_REF_PREFIX.length);
}
export function refForHydratedBlobUrl(blobUrl) {
    return blobUrlToRef.get(blobUrl);
}
function newBlobId() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return `blob-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
function openDb() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(PRIVATE_MEDIA_DB_NAME, DB_VERSION);
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
function dataUrlToBlob(dataUrl) {
    const [meta, b64] = dataUrl.split(",", 2);
    if (!b64)
        throw new Error("Invalid data URL.");
    const mime = meta.match(/^data:(.*?);base64$/)?.[1] || "application/octet-stream";
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1)
        bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mime });
}
async function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("Could not read private media blob."));
        reader.readAsDataURL(blob);
    });
}
async function readBlob(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const req = tx.objectStore(STORE_NAME).get(id);
        req.onerror = () => reject(req.error ?? new Error("Could not read private media."));
        req.onsuccess = () => resolve(req.result ?? null);
        tx.oncomplete = () => db.close();
        tx.onerror = () => {
            db.close();
            reject(tx.error ?? new Error("Could not read private media."));
        };
    });
}
/** Store a data URL or Blob; returns a stable `private-blob://` ref for localStorage JSON. */
export async function storePrivateBlob(dataUrlOrBlob) {
    const blob = typeof dataUrlOrBlob === "string" ? dataUrlToBlob(dataUrlOrBlob) : dataUrlOrBlob;
    const id = newBlobId();
    const db = await openDb();
    await new Promise((resolve, reject) => {
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
export async function resolvePrivateBlobRef(ref) {
    if (!isPrivateBlobRef(ref))
        return ref;
    const id = privateBlobRefId(ref);
    const blob = await readBlob(id);
    if (!blob)
        throw new Error("Private media not found in this browser.");
    const blobUrl = URL.createObjectURL(blob);
    blobUrlToRef.set(blobUrl, ref);
    return blobUrl;
}
export async function deletePrivateBlob(id) {
    const db = await openDb();
    await new Promise((resolve, reject) => {
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
/** Delete all IndexedDB media kept for browser-only Private Mode. */
export async function clearPrivateMediaStore() {
    for (const blobUrl of blobUrlToRef.keys())
        URL.revokeObjectURL(blobUrl);
    blobUrlToRef.clear();
    await new Promise((resolve, reject) => {
        const req = indexedDB.deleteDatabase(PRIVATE_MEDIA_DB_NAME);
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error ?? new Error("Could not clear private media storage."));
        req.onblocked = () => resolve();
    });
}
/** Persist an in-memory media URL (data:, blob:, or existing ref) as a private blob ref. */
export async function storePrivateMediaUrl(url) {
    const trimmed = url.trim();
    if (!trimmed)
        return trimmed;
    if (isPrivateBlobRef(trimmed))
        return trimmed;
    const existingRef = refForHydratedBlobUrl(trimmed);
    if (existingRef)
        return existingRef;
    if (trimmed.startsWith("data:"))
        return storePrivateBlob(trimmed);
    if (trimmed.startsWith("blob:")) {
        const blob = await fetch(trimmed).then((r) => r.blob());
        return storePrivateBlob(blob);
    }
    return trimmed;
}
/** Resolve private refs / blob URLs to a data URL suitable for upstream APIs. */
export async function resolvePrivateMediaUrlForApi(url) {
    const trimmed = url.trim();
    if (!trimmed)
        return trimmed;
    if (trimmed.startsWith("data:") || trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
        return trimmed;
    }
    if (isPrivateBlobRef(trimmed)) {
        const blob = await readBlob(privateBlobRefId(trimmed));
        if (!blob)
            throw new Error("Private media not found in this browser.");
        return blobToDataUrl(blob);
    }
    if (trimmed.startsWith("blob:")) {
        const blob = await fetch(trimmed).then((r) => r.blob());
        return blobToDataUrl(blob);
    }
    return trimmed;
}
export function isQuotaExceededError(err) {
    if (!err || typeof err !== "object")
        return false;
    const name = err.name;
    if (name === "QuotaExceededError")
        return true;
    const code = err.code;
    return code === 22 || code === 1014;
}
