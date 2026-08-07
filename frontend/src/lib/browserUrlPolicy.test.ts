import { describe, expect, it } from "vitest";
import { inertBrowserUrl, safeBrowserUrl } from "./browserUrlPolicy";
import { isAlphaRouterMediaFileUrl } from "./mediaUrl";

const BASE = "http://localhost:8080/admin/chat";

describe("safeBrowserUrl", () => {
  it("allows same-origin paths and secure external navigation", () => {
    expect(safeBrowserUrl("/api/chat/media/1/file", "image", BASE)).toBe(
      "/api/chat/media/1/file",
    );
    expect(safeBrowserUrl("https://docs.example.com/page", "navigation", BASE)).toBe(
      "https://docs.example.com/page",
    );
    expect(safeBrowserUrl("mailto:user@example.com", "navigation", BASE)).toBe(
      "mailto:user@example.com",
    );
  });

  it("blocks executable schemes, credentials, and insecure external HTTP", () => {
    for (const value of [
      "javascript:alert(1)",
      "java\tscript:alert(1)",
      "vbscript:msgbox(1)",
      "file:///etc/passwd",
      "https://user:secret@example.com/path",
      "http://example.com/image.png",
    ]) {
      expect(safeBrowserUrl(value, "navigation", BASE)).toBeNull();
    }
    expect(inertBrowserUrl("javascript:alert(1)", "navigation")).toBe("#");
  });

  it("allows raster data images but blocks SVG and active data payloads", () => {
    expect(safeBrowserUrl("data:image/png;base64,AAAA", "image", BASE)).toBe(
      "data:image/png;base64,AAAA",
    );
    expect(
      safeBrowserUrl(
        "data:image/svg+xml,<svg onload='alert(1)'></svg>",
        "image",
        BASE,
      ),
    ).toBeNull();
    expect(safeBrowserUrl("data:text/html,<script>alert(1)</script>", "image", BASE)).toBeNull();
  });

  it("limits blob and media data URLs to media contexts", () => {
    expect(safeBrowserUrl("blob:http://localhost:8080/id", "image", BASE)).toBeTruthy();
    expect(safeBrowserUrl("blob:http://localhost:8080/id", "navigation", BASE)).toBeNull();
    expect(safeBrowserUrl("data:audio/mpeg;base64,AAAA", "media", BASE)).toBeTruthy();
    expect(safeBrowserUrl("data:audio/mpeg;base64,AAAA", "image", BASE)).toBeNull();
  });
});

describe("authenticated media URL scope", () => {
  it("only recognizes the same-origin Alpharouter media route", () => {
    expect(isAlphaRouterMediaFileUrl("/api/chat/media/42/file?download=1")).toBe(true);
    expect(isAlphaRouterMediaFileUrl("https://evil.example/api/chat/media/42/file")).toBe(false);
    expect(isAlphaRouterMediaFileUrl("/api/chat/media/not-an-id/file")).toBe(false);
  });
});
