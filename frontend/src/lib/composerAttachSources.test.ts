import { describe, expect, it, vi } from "vitest";
import * as apiMod from "../api";
import {
  attachMediaIds,
  attachSlotOverflowMessage,
  capAttachSelection,
  composerAttachEligibility,
  mediaBlobToFile,
  normalizeProjectMediaItem,
  normalizeUserMediaItem,
  type ComposerAttachMediaCandidate,
} from "./composerAttachSources";
import type { MediaItem } from "./mediaLibrary";
import type { ProjectMediaItem } from "./projectsApi";

function candidate(partial: Partial<ComposerAttachMediaCandidate>): ComposerAttachMediaCandidate {
  return {
    id: 1,
    kind: "image",
    fileName: "shot.png",
    mimeType: "image/png",
    url: "/api/chat/media/1/file",
    ...partial,
  };
}

describe("composerAttachEligibility", () => {
  it("allows images", () => {
    expect(composerAttachEligibility(candidate({}), { privateMode: false })).toEqual({
      attachable: true,
      reason: null,
      processedKind: "image",
    });
  });

  it("allows documents outside Private Mode", () => {
    expect(
      composerAttachEligibility(
        candidate({ kind: "document", fileName: "brief.pdf", mimeType: "application/pdf" }),
        { privateMode: false },
      ),
    ).toEqual({
      attachable: true,
      reason: null,
      processedKind: "document",
    });
  });

  it("blocks video by kind or mime", () => {
    expect(
      composerAttachEligibility(
        candidate({ kind: "video", fileName: "clip.mp4", mimeType: "video/mp4" }),
        { privateMode: false },
      ).attachable,
    ).toBe(false);
    expect(
      composerAttachEligibility(
        candidate({ kind: "other", fileName: "clip.bin", mimeType: "video/webm" }),
        { privateMode: false },
      ).reason,
    ).toMatch(/Video/);
  });

  it("blocks SVG and other disallowed types", () => {
    expect(
      composerAttachEligibility(
        candidate({ kind: "image", fileName: "icon.svg", mimeType: "image/svg+xml" }),
        { privateMode: false },
      ).attachable,
    ).toBe(false);
  });

  it("in Private Mode allows images and plain text only", () => {
    expect(
      composerAttachEligibility(candidate({ fileName: "note.txt", kind: "document", mimeType: "text/plain" }), {
        privateMode: true,
      }).attachable,
    ).toBe(true);
    expect(
      composerAttachEligibility(
        candidate({ kind: "document", fileName: "brief.pdf", mimeType: "application/pdf" }),
        { privateMode: true },
      ).attachable,
    ).toBe(false);
  });
});

describe("capAttachSelection", () => {
  it("toggles an id off without using a slot", () => {
    expect(capAttachSelection([1, 2], 2, 1)).toEqual({ ids: [1], blocked: false });
  });

  it("adds an id when a slot remains", () => {
    expect(capAttachSelection([1], 9, 2)).toEqual({ ids: [1, 9], blocked: false });
  });

  it("blocks adding past remaining slots", () => {
    expect(capAttachSelection([1, 2], 3, 2)).toEqual({ ids: [1, 2], blocked: true });
    expect(capAttachSelection([], 3, 0)).toEqual({ ids: [], blocked: true });
  });
});

describe("attachSlotOverflowMessage", () => {
  it("describes remaining slots", () => {
    expect(attachSlotOverflowMessage(0)).toMatch(/no more files/i);
    expect(attachSlotOverflowMessage(1)).toBe("You can attach 1 more file.");
    expect(attachSlotOverflowMessage(3)).toBe("You can attach up to 3 more files.");
  });
});

describe("media item normalizers", () => {
  it("maps personal and project media onto the same candidate shape", () => {
    const user: MediaItem = {
      id: 4,
      kind: "image",
      mime_type: "image/png",
      file_name: "a.png",
      size_bytes: 12,
      url: "/api/chat/media/4/file",
      created_at: "2026-01-01T00:00:00Z",
    };
    const project: ProjectMediaItem = {
      id: 8,
      projectId: "p1",
      kind: "document",
      mimeType: "application/pdf",
      fileName: "b.pdf",
      sizeBytes: 20,
      storagePath: "x",
      url: "/api/projects/p1/media/8/download",
      createdAt: "2026-01-02T00:00:00Z",
    };
    expect(normalizeUserMediaItem(user).fileName).toBe("a.png");
    expect(normalizeProjectMediaItem(project).fileName).toBe("b.pdf");
  });
});

describe("attachMediaIds", () => {
  it("posts unique positive ids to from-media", async () => {
    const spy = vi.spyOn(apiMod, "api").mockResolvedValue({
      attachments: [
        { name: "a.png", kind: "image", mime_type: "image/png", url: "/api/chat/media/1/file" },
      ],
    });
    try {
      const out = await attachMediaIds({
        mediaIds: [1, 1, 0, -2],
        chatSessionId: "sess-1",
        projectId: "proj-1",
      });
      expect(out).toHaveLength(1);
      expect(spy).toHaveBeenCalledWith(
        "/api/chat/attachments/from-media",
        expect.objectContaining({ method: "POST" }),
      );
      const body = JSON.parse(String(spy.mock.calls[0][1]?.body));
      expect(body).toEqual({
        media_ids: [1],
        chat_session_id: "sess-1",
        project_id: "proj-1",
      });
    } finally {
      spy.mockRestore();
    }
  });
});

describe("mediaBlobToFile", () => {
  it("keeps the filename and adds an extension when missing", () => {
    const blob = new Blob(["x"], { type: "image/png" });
    const named = mediaBlobToFile(blob, candidate({ fileName: "shot.png" }));
    expect(named.name).toBe("shot.png");
    expect(named.type).toBe("image/png");
    const inferred = mediaBlobToFile(blob, candidate({ fileName: "shot", mimeType: "image/jpeg" }));
    expect(inferred.name).toBe("shot.jpeg");
  });
});
