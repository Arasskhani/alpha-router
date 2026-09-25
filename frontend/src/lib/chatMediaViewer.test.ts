import { describe, expect, it } from "vitest";
import { attachmentMessage } from "./chatAttachments";
import { buildImageMessage } from "./chatImage";
import { collectChatSlideshowItems } from "./chatMediaViewer";
import { buildVideoMessage } from "./chatVideo";
import { findMediaViewerIndex } from "./mediaViewer";
import { IMAGE_PENDING_MARKER, VIDEO_PENDING_MARKER } from "./chatMarkers";

describe("collectChatSlideshowItems", () => {
  it("leaves out the images of an answer built from a shared page, which are never loaded", () => {
    const items = collectChatSlideshowItems([
      { content: "Chart: ![c](https://tracker.example/p.png?d=secret)", pageContext: { sites: ["docs.example.com"] } },
      { content: "Here you go\n\n![out](https://cdn.example.test/out.png)" },
    ]);
    expect(items.map((item) => item.url)).toEqual(["https://cdn.example.test/out.png"]);
  });

  it("walks the thread in order and mixes attachments, images, and videos", () => {
    const items = collectChatSlideshowItems([
      {
        content: attachmentMessage({
          userText: "refs",
          attachments: [
            {
              name: "one.png",
              kind: "image",
              mime_type: "image/png",
              url: "/api/chat/media/1/file",
            },
            {
              name: "notes.pdf",
              kind: "document",
              mime_type: "application/pdf",
              url: "/api/chat/media/2/file",
            },
            {
              name: "two.png",
              kind: "image",
              mime_type: "image/png",
              url: "",
              data_url: "data:image/png;base64,abc",
            },
          ],
        }),
      },
      { content: "plain text" },
      { content: IMAGE_PENDING_MARKER },
      {
        content: buildImageMessage({
          url: "/api/chat/media/9/file",
          prompt: "a lake",
          model: "image-model",
        }),
      },
      { content: VIDEO_PENDING_MARKER },
      {
        content: buildVideoMessage({
          url: "/api/videos/jobs/11111111-1111-1111-1111-111111111111/private-file",
          prompt: "waves",
          model: "video-model",
        }),
      },
      { content: "Here you go\n\n![out](https://cdn.example.test/out.png)" },
    ]);

    expect(items.map((item) => item.url)).toEqual([
      "/api/chat/media/1/file",
      "data:image/png;base64,abc",
      "/api/chat/media/9/file",
      "/api/videos/jobs/11111111-1111-1111-1111-111111111111/private-file",
      "https://cdn.example.test/out.png",
    ]);
    expect(items.map((item) => item.kind)).toEqual(["image", "image", "image", "video", "image"]);
    expect(findMediaViewerIndex(items, "/api/chat/media/9/file")).toBe(2);
  });

  it("ignores empty and unreadable payloads", () => {
    expect(
      collectChatSlideshowItems([
        { content: "" },
        { content: "__ALPHA_ROUTER_IMAGE_JSON__:{not-json" },
        { content: attachmentMessage({ userText: "", attachments: [] }) },
      ]),
    ).toEqual([]);
  });
});
