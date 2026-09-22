/**
 * The operator's file-type policy, mirrored in the browser: the same name rules
 * as the server, the same wording, and nothing refused on the client that the
 * server would not refuse too.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as apiMod from "../api";
import {
  classifyFileName,
  fetchAttachmentPolicy,
  formatFileSize,
  resetAttachmentPolicyCache,
  type AttachmentPolicy,
} from "./attachmentPolicy";
import {
  PRIVATE_MODE_ATTACHMENT_MESSAGE,
  attachmentDisplayText,
  attachmentFileNotes,
  attachmentMessage,
  buildApiMessageContent,
  canProcessAttachmentLocally,
  processAttachmentFilesLocally,
  validateAttachmentFile,
} from "./chatAttachments";

function policy(partial: Partial<AttachmentPolicy> = {}): AttachmentPolicy {
  return {
    mode: "blocklist",
    blocked: new Set(["exe", "zip", "py", "svg"]),
    allowed: new Set(["pdf", "png", "psd"]),
    maxAttachments: 5,
    maxUploadMb: 25,
    ...partial,
  };
}

describe("classifyFileName", () => {
  describe("blocklist mode", () => {
    const p = policy();

    it("refuses when any suffix is blocked, naming that suffix", () => {
      expect(classifyFileName("report.pdf.exe", p)).toEqual({
        ok: false,
        reason: 'File type ".exe" is not allowed on this platform.',
      });
      expect(classifyFileName("photo.exe.jpg", p)).toEqual({
        ok: false,
        reason: 'File type ".exe" is not allowed on this platform.',
      });
    });

    it("gives an unknown format the kind file", () => {
      expect(classifyFileName("x.psd", p)).toEqual({ ok: true, ext: "psd", kind: "file" });
    });

    it("detects kind case-insensitively", () => {
      expect(classifyFileName("Photo.PNG", p)).toEqual({ ok: true, ext: "png", kind: "image" });
      expect(classifyFileName("Clip.MOV", p)).toEqual({ ok: true, ext: "mov", kind: "video" });
      expect(classifyFileName("song.Mp3", p)).toEqual({ ok: true, ext: "mp3", kind: "audio" });
      expect(classifyFileName("notes.md", p)).toEqual({ ok: true, ext: "md", kind: "document" });
    });

    it("refuses a name without an extension", () => {
      expect(classifyFileName("README", p)).toEqual({ ok: false, reason: "Files must have an extension." });
      expect(classifyFileName("", p)).toEqual({ ok: false, reason: "Files must have an extension." });
    });
  });

  describe("allowlist mode", () => {
    const p = policy({ mode: "allowlist" });

    it("requires the last suffix to be allowed, with the allowlist wording", () => {
      expect(classifyFileName("a.txt", p)).toEqual({
        ok: false,
        reason: 'File type ".txt" is not on the list of allowed file types.',
      });
      expect(classifyFileName("a.pdf", p)).toEqual({ ok: true, ext: "pdf", kind: "document" });
    });

    it("lets the blocklist win over the allowlist", () => {
      expect(classifyFileName("a.exe.pdf", p)).toEqual({
        ok: false,
        reason: 'File type ".exe" is not allowed on this platform.',
      });
    });
  });

  describe("without a policy", () => {
    it("refuses only a missing extension; the server decides the rest", () => {
      expect(classifyFileName("setup.exe", null)).toEqual({ ok: true, ext: "exe", kind: "file" });
      expect(classifyFileName("x.psd", null)).toEqual({ ok: true, ext: "psd", kind: "file" });
      expect(classifyFileName("noext", null)).toEqual({ ok: false, reason: "Files must have an extension." });
    });
  });
});

describe("fetchAttachmentPolicy", () => {
  afterEach(() => {
    resetAttachmentPolicyCache();
    vi.restoreAllMocks();
  });

  it("fetches once and serves the cached policy afterwards", async () => {
    const spy = vi.spyOn(apiMod, "api").mockResolvedValue({
      mode: "allowlist",
      blocked: ["EXE", ".zip"],
      allowed: ["pdf"],
      max_attachments: 3,
      max_upload_mb: 10,
    });
    const first = await fetchAttachmentPolicy();
    const second = await fetchAttachmentPolicy();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("/api/chat/attachment-policy");
    expect(second).toBe(first);
    expect(first).toEqual({
      mode: "allowlist",
      blocked: new Set(["exe", "zip"]),
      allowed: new Set(["pdf"]),
      maxAttachments: 3,
      maxUploadMb: 10,
    });
  });

  it("de-duplicates concurrent requests", async () => {
    const spy = vi.spyOn(apiMod, "api").mockResolvedValue({ mode: "blocklist", blocked: [], allowed: [] });
    const [a, b] = await Promise.all([fetchAttachmentPolicy(), fetchAttachmentPolicy()]);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("returns null when the request fails and does not cache the failure", async () => {
    const spy = vi.spyOn(apiMod, "api").mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({
      mode: "blocklist",
      blocked: ["exe"],
      allowed: [],
    });
    expect(await fetchAttachmentPolicy()).toBeNull();
    expect(await fetchAttachmentPolicy()).toMatchObject({ mode: "blocklist" });
    expect(spy).toHaveBeenCalledTimes(2);
  });
});

describe("validateAttachmentFile", () => {
  it("throws the server's wording", () => {
    expect(() => validateAttachmentFile(new File(["x"], "setup.exe"), policy())).toThrow(
      'File type ".exe" is not allowed on this platform.',
    );
    expect(() => validateAttachmentFile(new File(["x"], "a.txt"), policy({ mode: "allowlist" }))).toThrow(
      'File type ".txt" is not on the list of allowed file types.',
    );
    expect(() => validateAttachmentFile(new File(["x"], "noext"), null)).toThrow("Files must have an extension.");
  });

  it("lets an unknown format through when the policy allows it", () => {
    expect(() => validateAttachmentFile(new File(["x"], "x.psd"), policy())).not.toThrow();
    expect(() => validateAttachmentFile(new File(["x"], "setup.exe"), null)).not.toThrow();
  });
});

describe("canProcessAttachmentLocally", () => {
  it("accepts media and text-suffixed files of any kind, not binary ones", () => {
    expect(canProcessAttachmentLocally("photo.webp")).toBe(true);
    expect(canProcessAttachmentLocally("notes.txt")).toBe(true);
    expect(canProcessAttachmentLocally("brief.pdf")).toBe(false);
    expect(canProcessAttachmentLocally("x.psd")).toBe(false);
  });
});

describe("processAttachmentFilesLocally (Private Mode)", () => {
  it("refuses a binary unknown format with the Private Mode message", async () => {
    await expect(processAttachmentFilesLocally([new File([new Uint8Array([0, 1, 2])], "x.psd")])).rejects.toThrow(
      PRIVATE_MODE_ATTACHMENT_MESSAGE,
    );
    expect(PRIVATE_MODE_ATTACHMENT_MESSAGE).toBe(
      "In Private Mode only images, audio, video and text files can be attached.",
    );
  });

  it("refuses a binary document the same way", async () => {
    await expect(processAttachmentFilesLocally([new File(["%PDF"], "brief.pdf")])).rejects.toThrow(
      PRIVATE_MODE_ATTACHMENT_MESSAGE,
    );
  });

  it("reads an unblocked source file as text with kind file", async () => {
    const unblocked = policy({ blocked: new Set(["exe"]) });
    const [py] = await processAttachmentFilesLocally([new File(["print(1)\n"], "script.py")], unblocked);
    expect(py).toMatchObject({ name: "script.py", kind: "file", text: "print(1)\n", url: "", size_bytes: 9 });
  });

  it("still applies the policy before reading", async () => {
    await expect(processAttachmentFilesLocally([new File(["print(1)"], "script.py")], policy())).rejects.toThrow(
      'File type ".py" is not allowed on this platform.',
    );
  });

  it("keeps text documents as documents", async () => {
    const [md] = await processAttachmentFilesLocally([new File(["# hi"], "notes.md")]);
    expect(md).toMatchObject({ kind: "document", text: "# hi" });
  });
});

describe("model content for documents and files", () => {
  it("includes a file's text like a document's", () => {
    const content = attachmentMessage({
      userText: "Look",
      attachments: [
        { name: "a.py", kind: "file", mime_type: "text/x-python", url: "", text: "print(1)" },
        { name: "b.md", kind: "document", mime_type: "text/markdown", url: "", text: "# b" },
      ],
    });
    expect(buildApiMessageContent(content)).toBe("Look\n\n--- a.py ---\nprint(1)\n\n--- b.md ---\n# b");
  });

  it("appends the binary note with the size when no text was extracted", () => {
    const content = attachmentMessage({
      userText: "See attached",
      attachments: [
        {
          name: "design.psd",
          kind: "file",
          mime_type: "application/octet-stream",
          url: "/api/chat/media/7/file",
          text: null,
          binary: true,
          size_bytes: 1_258_291,
        },
      ],
    });
    expect(buildApiMessageContent(content)).toBe(
      "See attached\n\n" +
        '[Attached file "design.psd" (1.2 MB, binary): no text was extracted. ' +
        "It is available in the Code Interpreter workspace when that tool is enabled.]",
    );
  });

  it("notes a binary document too, and says binary alone when the size is unknown", () => {
    expect(
      attachmentFileNotes([
        { name: "scan.pdf", kind: "document", mime_type: "application/pdf", url: "/api/chat/media/8/file", text: null },
      ]),
    ).toEqual([
      '[Attached file "scan.pdf" (binary): no text was extracted. ' +
        "It is available in the Code Interpreter workspace when that tool is enabled.]",
    ]);
  });

  it("counts files in the display text", () => {
    expect(
      attachmentDisplayText({
        userText: "",
        attachments: [{ name: "x.psd", kind: "file", mime_type: "", url: "" }],
      }),
    ).toBe("📎 x.psd");
  });
});

describe("formatFileSize", () => {
  it("picks a readable unit", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(1_258_291)).toBe("1.2 MB");
    expect(formatFileSize(150 * 1024 * 1024)).toBe("150 MB");
  });
});

describe("ChatPanel wiring", () => {
  it("no longer pre-filters the picker and asks for the policy before validating", () => {
    // ChatPanel is too large to mount here; the wiring is a string.
    const sources = import.meta.glob("../components/ChatPanel.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const panel = sources["../components/ChatPanel.tsx"] ?? "";
    expect(panel.length).toBeGreaterThan(0);
    expect(panel).not.toContain("accept={ATTACHMENT_ACCEPT}");
    expect(panel).not.toContain("ATTACHMENT_ACCEPT");
    expect(panel).toContain("fetchAttachmentPolicy(");
    expect(panel).toContain("validateAttachmentFile(file, policy)");
  });
});
