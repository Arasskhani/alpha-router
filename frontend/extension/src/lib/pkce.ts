/**
 * PKCE (RFC 7636, S256) and the connect attempt's state value.
 *
 * The verifier never leaves the extension until the code exchange; the server
 * only ever sees its SHA-256. A stolen connect code is useless without it.
 */

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

/** 32 random bytes: a 43-character verifier, the shortest RFC 7636 allows and plenty. */
export function createVerifier(): string {
  return randomString(32);
}

/** A state value for one connect attempt: 22 characters of [A-Za-z0-9_-]. */
export function createState(): string {
  return randomString(16);
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}
