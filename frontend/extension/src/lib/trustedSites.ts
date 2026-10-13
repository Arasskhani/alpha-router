/**
 * The sites a person trusts the agent on, across runs: kept in this browser
 * (chrome.storage.local), added from an approval card and removed from the
 * Agent tab. On a trusted site the agent's plain actions go ahead without a
 * card; what always asks still asks, and the administrator can turn trust
 * off for everyone (policy.trusted_sites).
 */

import { siteOf } from "./sites";

export const TRUSTED_SITES_KEY = "alpharouter.trustedSites";
/** A list a person keeps by hand: more than this many is no longer a choice they could review. */
const MAX_TRUSTED = 50;

function clean(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const sites = value.filter((v): v is string => typeof v === "string" && /^[a-z0-9.[\]:_-]{1,253}$/i.test(v)).map((v) => siteOf(v));
  return [...new Set(sites)].slice(0, MAX_TRUSTED);
}

export async function loadTrustedSites(): Promise<string[]> {
  try {
    const stored = await chrome.storage.local.get(TRUSTED_SITES_KEY);
    return clean(stored[TRUSTED_SITES_KEY]);
  } catch {
    return [];
  }
}

async function saveTrustedSites(sites: string[]): Promise<string[]> {
  const kept = clean(sites);
  await chrome.storage.local.set({ [TRUSTED_SITES_KEY]: kept });
  return kept;
}

export async function trustSite(site: string): Promise<string[]> {
  const now = await loadTrustedSites();
  return saveTrustedSites([...now.filter((s) => s !== siteOf(site)), siteOf(site)]);
}

export async function untrustSite(site: string): Promise<string[]> {
  return saveTrustedSites((await loadTrustedSites()).filter((s) => s !== siteOf(site)));
}
