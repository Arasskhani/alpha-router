/**
 * @vitest-environment happy-dom
 *
 * A sent message with attachments: files the platform cannot parse sit beside
 * documents as chips — name, size, "no preview" when no text came out, and a
 * download when the server kept the bytes.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const downloadAuthenticatedMedia = vi.hoisted(() => vi.fn(async () => undefined));

vi.mock("../MarkdownContent", () => ({ downloadAuthenticatedMedia }));
vi.mock("../AuthenticatedImage", () => ({ default: () => null }));
vi.mock("../AuthenticatedVideo", () => ({ default: () => null }));
vi.mock("../AuthenticatedAudio", () => ({ default: () => null }));

import ChatAttachmentMessage from "./ChatAttachmentMessage";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  downloadAuthenticatedMedia.mockClear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

describe("ChatAttachmentMessage", () => {
  it("renders a binary file as a chip with size, no preview and a download", async () => {
    await act(async () => {
      root.render(
        <ChatAttachmentMessage
          payload={{
            userText: "Here",
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
              { name: "brief.pdf", kind: "document", mime_type: "application/pdf", url: "/api/chat/media/8/file" },
            ],
          }}
        />,
      );
    });
    const chip = host.querySelector(".chat-attachment-file");
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toContain("design.psd");
    expect(chip?.textContent).toContain("1.2 MB");
    expect(chip?.textContent).toContain("no preview");
    expect(chip?.querySelector("svg")).not.toBeNull();

    const links = [...host.querySelectorAll("a.alpha-router-attach-msg__download")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/api/chat/media/8/file", "/api/chat/media/7/file"]);

    await act(async () => {
      links[1].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(downloadAuthenticatedMedia).toHaveBeenCalledWith("/api/chat/media/7/file", "design.psd");
  });

  it("omits size, no preview and download for a text file read in the browser", async () => {
    await act(async () => {
      root.render(
        <ChatAttachmentMessage
          payload={{
            userText: "",
            attachments: [{ name: "script.py", kind: "file", mime_type: "text/x-python", url: "", text: "print(1)" }],
          }}
        />,
      );
    });
    const chip = host.querySelector(".chat-attachment-file");
    expect(chip?.textContent).toBe("script.py");
    expect(host.querySelector(".alpha-router-attach-msg__download")).toBeNull();
    expect(host.textContent).not.toContain("📎");
  });
});
