import { describe, expect, it } from "vitest";
import {
  findMediaViewerIndex,
  isSlideshowMediaKind,
  slideshowItemsFromMedia,
} from "./mediaViewer";

describe("isSlideshowMediaKind", () => {
  it("accepts image and video only", () => {
    expect(isSlideshowMediaKind("image")).toBe(true);
    expect(isSlideshowMediaKind("video")).toBe(true);
    expect(isSlideshowMediaKind("document")).toBe(false);
    expect(isSlideshowMediaKind("other")).toBe(false);
  });
});

describe("slideshowItemsFromMedia", () => {
  it("keeps gallery order and skips documents", () => {
    const items = slideshowItemsFromMedia([
      { id: 3, kind: "image", url: "/api/chat/media/3/file", file_name: "a.png", source_prompt: "cat" },
      { id: 2, kind: "document", url: "/api/chat/media/2/file", file_name: "notes.pdf" },
      { id: 1, kind: "video", url: "/api/chat/media/1/file", file_name: "clip.mp4" },
    ]);

    expect(items).toEqual([
      {
        id: "media-3",
        url: "/api/chat/media/3/file",
        kind: "image",
        alt: "a.png",
        title: "cat",
      },
      {
        id: "media-1",
        url: "/api/chat/media/1/file",
        kind: "video",
        alt: "clip.mp4",
        title: "clip.mp4",
      },
    ]);
  });

  it("finds the opened file by url", () => {
    const items = slideshowItemsFromMedia([
      { id: 9, kind: "image", url: "/img/9", file_name: "nine.png" },
      { id: 8, kind: "video", url: "/vid/8", file_name: "eight.mp4" },
    ]);
    expect(findMediaViewerIndex(items, "/vid/8")).toBe(1);
    expect(findMediaViewerIndex(items, "/missing")).toBe(-1);
  });
});
