/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const media = vi.hoisted(() => ({ fetchAuthenticatedMediaObjectUrl: vi.fn() }));
vi.mock("../lib/mediaUrl", () => ({
  fetchAuthenticatedMediaObjectUrl: media.fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl: (url: string) => /^\/api\/chat\/media\/\d+\/file$/.test(url),
}));

import { useAuthenticatedMediaSource } from "./useAuthenticatedMediaSource";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let seen: { src: string | null; failed: boolean }[] = [];

function Probe({ url }: { url: string }) {
  const state = useAuthenticatedMediaSource(url, "image");
  seen.push(state);
  return <span data-src={state.src ?? ""} data-failed={String(state.failed)} />;
}

function render(url: string) {
  act(() => {
    root.render(<Probe url={url} />);
  });
}
const latest = () => seen[seen.length - 1];

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  seen = [];
  media.fetchAuthenticatedMediaObjectUrl.mockReset();
  if (!("revokeObjectURL" in URL)) Object.assign(URL, { revokeObjectURL: () => {} });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("useAuthenticatedMediaSource", () => {
  it("uses a plain URL directly, without a fetch", () => {
    render("https://example.com/a.png");
    expect(latest()).toEqual({ src: "https://example.com/a.png", failed: false });
    expect(media.fetchAuthenticatedMediaObjectUrl).not.toHaveBeenCalled();
  });

  it("fetches an Alpharouter media URL and ignores the result once the URL has changed", async () => {
    let resolveFirst!: (v: string) => void;
    media.fetchAuthenticatedMediaObjectUrl
      .mockImplementationOnce(() => new Promise<string>((r) => (resolveFirst = r)))
      .mockImplementationOnce(() => Promise.resolve("blob:second"));

    render("/api/chat/media/1/file");
    expect(latest().src).toBeNull();

    render("/api/chat/media/2/file");
    await act(async () => {
      await Promise.resolve();
    });
    expect(latest().src).toBe("blob:second");

    // The first fetch finally answers. It belongs to a URL no longer shown.
    await act(async () => {
      resolveFirst("blob:first");
      await Promise.resolve();
    });
    expect(latest().src, "a stale result for the old URL is not shown").toBe("blob:second");
    expect(URL.revokeObjectURL, "and its object URL is released").toHaveBeenCalledWith("blob:first");
  });

  it("reports failure for the URL that failed, and nothing for an empty one", async () => {
    media.fetchAuthenticatedMediaObjectUrl.mockRejectedValueOnce(new Error("401"));
    render("/api/chat/media/3/file");
    await act(async () => {
      await Promise.resolve();
    });
    expect(latest()).toEqual({ src: null, failed: true });

    render("");
    expect(latest()).toEqual({ src: null, failed: false });
  });
});
