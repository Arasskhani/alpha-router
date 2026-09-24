/**
 * @vitest-environment happy-dom
 *
 * What makes Alpharouter installable: the web app manifest, its icons, the
 * head tags iOS and Android read, and a Home Screen icon that stays a PNG.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { APPLE_TOUCH_ICON, applyBlankFavicon } from "./favicon";

const FRONTEND = join(__dirname, "..", "..");
const PUBLIC = join(FRONTEND, "public");

type Icon = { src: string; sizes: string; type: string; purpose: string };
const manifest = JSON.parse(readFileSync(join(PUBLIC, "manifest.webmanifest"), "utf8")) as {
  id: string;
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  prefer_related_applications?: boolean;
  icons: Icon[];
};

/** Width, height and PNG colour type, from the IHDR chunk. */
function png(path: string): { width: number; height: number; colourType: number } {
  const bytes = readFileSync(path);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(bytes.subarray(12, 16).toString("latin1")).toBe("IHDR");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20), colourType: bytes[25] };
}

describe("the web app manifest", () => {
  it("has what Chrome needs to offer installing", () => {
    expect(manifest.name).toBe("Alpharouter");
    expect(manifest.short_name).toBe("Alpharouter");
    expect(manifest.start_url).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.prefer_related_applications).not.toBe(true);
    const any = manifest.icons.filter((i) => i.purpose === "any").map((i) => i.sizes);
    expect(any).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  });

  it("fixes the app's identity and scope, so a later start_url change is not a second app", () => {
    expect(manifest.id).toBe("/");
    expect(manifest.scope).toBe("/");
  });

  it("has maskable icons for Android's shaped launchers", () => {
    const maskable = manifest.icons.filter((i) => i.purpose === "maskable").map((i) => i.sizes);
    expect(maskable).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  });

  it("points at icons that exist, at the size it declares", () => {
    for (const icon of manifest.icons) {
      expect(icon.type).toBe("image/png");
      const { width, height } = png(join(PUBLIC, icon.src));
      expect(`${width}x${height}`).toBe(icon.sizes);
    }
  });
});

describe("the Home Screen icon for iOS", () => {
  it("is a 180px PNG without transparency, which iOS would paint black", () => {
    const { width, height, colourType } = png(join(PUBLIC, "icons", "apple-touch-icon.png"));
    expect([width, height]).toEqual([180, 180]);
    // 2 = RGB, 0 = greyscale: no alpha channel.
    expect([0, 2]).toContain(colourType);
  });

  it("stays the PNG after the favicons are applied at start-up", () => {
    document.head.innerHTML = '<link rel="apple-touch-icon" href="/favicon.svg?v=4">';
    applyBlankFavicon();
    const touch = document.head.querySelectorAll<HTMLLinkElement>('link[rel="apple-touch-icon"]');
    expect(touch).toHaveLength(1);
    expect(touch[0].getAttribute("href")).toBe(APPLE_TOUCH_ICON);
    expect(APPLE_TOUCH_ICON).toBe("/icons/apple-touch-icon.png");
  });
});

describe("index.html", () => {
  const html = readFileSync(join(FRONTEND, "index.html"), "utf8");
  const tag = (pattern: RegExp) => expect(html).toMatch(pattern);

  it("links the manifest and the PNG touch icon", () => {
    tag(/<link rel="manifest" href="\/manifest\.webmanifest"/);
    tag(/<link rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png"/);
    expect(html).not.toMatch(/rel="apple-touch-icon" href="[^"]*\.svg/);
  });

  it("names the app on the iOS Home Screen instead of using the whole page title", () => {
    tag(/<meta name="apple-mobile-web-app-title" content="Alpharouter"/);
  });

  it("keeps the status bar readable and tints it per colour scheme", () => {
    tag(/<meta name="mobile-web-app-capable" content="yes"/);
    tag(/<meta name="apple-mobile-web-app-status-bar-style" content="default"/);
    tag(/<meta name="theme-color" content="#ffffff" media="\(prefers-color-scheme: light\)"/);
    tag(/<meta name="theme-color" content="#12171e" media="\(prefers-color-scheme: dark\)"/);
  });
});
