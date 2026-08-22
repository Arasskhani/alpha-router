import { describe, expect, it } from "vitest";
import { isAlphaRouterMediaFileUrl } from "./mediaUrl";

describe("isAlphaRouterMediaFileUrl", () => {
  it("allows project media download URLs", () => {
    expect(isAlphaRouterMediaFileUrl("/api/projects/proj-abc/media/7/download")).toBe(true);
  });

  it("rejects off-origin media URLs", () => {
    expect(isAlphaRouterMediaFileUrl("https://evil.example/api/projects/x/media/1/download")).toBe(
      false,
    );
  });
});
