import { afterEach, describe, expect, it, vi } from "vitest";

const mediaMocks = vi.hoisted(() => ({
  fetchAuthenticatedMediaBlob: vi.fn(),
}));

vi.mock("../lib/mediaUrl", () => ({
  fetchAuthenticatedMediaBlob: mediaMocks.fetchAuthenticatedMediaBlob,
  isAlphaRouterMediaFileUrl: (url: string) => /^\/api\/chat\/media\/\d+\/file$/.test(url),
}));

import { downloadAuthenticatedMedia } from "./MarkdownContent";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  mediaMocks.fetchAuthenticatedMediaBlob.mockReset();
});

describe("authenticated Markdown media downloads", () => {
  it("fetches with the authenticated media helper and downloads the canonical filename", async () => {
    vi.useFakeTimers();
    const blob = new Blob(["pdf"], { type: "application/pdf" });
    mediaMocks.fetchAuthenticatedMediaBlob.mockResolvedValue(blob);
    const anchor = {
      href: "",
      download: "",
      click: vi.fn(),
      remove: vi.fn(),
    };
    const appendChild = vi.fn();
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("document", {
      createElement: vi.fn(() => anchor),
      body: { appendChild },
    });
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:report"),
      revokeObjectURL,
    });

    await downloadAuthenticatedMedia(
      "/api/chat/media/42/file",
      "management-report.pdf",
    );

    expect(mediaMocks.fetchAuthenticatedMediaBlob).toHaveBeenCalledWith(
      "/api/chat/media/42/file",
    );
    expect(anchor.href).toBe("blob:report");
    expect(anchor.download).toBe("management-report.pdf");
    expect(appendChild).toHaveBeenCalledWith(anchor);
    expect(anchor.click).toHaveBeenCalledOnce();
    expect(anchor.remove).toHaveBeenCalledOnce();
    await vi.runAllTimersAsync();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });
});
