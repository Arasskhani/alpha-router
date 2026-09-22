/**
 * @vitest-environment happy-dom
 *
 * Dropping files onto the chat pane must reach the same path as the picker,
 * and nothing else may: not a dragged sidebar chat, not a link, not a folder,
 * not a drop in the middle of a streaming reply.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  DROP_BUSY_MESSAGE,
  DROP_DIRECTORY_MESSAGE,
  dragCarriesFiles,
  dropOverflowMessage,
  filesFromDrop,
  useFileDrop,
  type UseFileDropOptions,
} from "./useFileDrop";

function file(name: string): File {
  return new File(["x"], name, { type: "text/plain" });
}

/** A DataTransfer stand-in: happy-dom has no constructor for the real one. */
function transfer(opts: { files?: File[]; types?: string[]; directories?: string[] }): DataTransfer {
  const files = opts.files ?? [];
  const types = opts.types ?? (files.length || opts.directories?.length ? ["Files"] : ["text/plain"]);
  const items = [
    ...files.map((f) => ({ kind: "file", getAsFile: () => f, webkitGetAsEntry: () => ({ isDirectory: false }) })),
    ...(opts.directories ?? []).map((name) => ({
      kind: "file",
      getAsFile: () => new File([], name),
      webkitGetAsEntry: () => ({ isDirectory: true }),
    })),
  ];
  return { types, files, items, dropEffect: "none" } as unknown as DataTransfer;
}

describe("dragCarriesFiles", () => {
  it("is true only for a drag that carries files", () => {
    expect(dragCarriesFiles(transfer({ files: [file("a.txt")] }))).toBe(true);
    expect(dragCarriesFiles(transfer({ types: ["text/plain"] }))).toBe(false);
    expect(dragCarriesFiles(transfer({ types: ["text/uri-list"] }))).toBe(false);
    expect(dragCarriesFiles(null)).toBe(false);
  });
});

describe("filesFromDrop", () => {
  it("returns the files and flags a folder instead of handing over an empty File", () => {
    const dt = transfer({ files: [file("a.txt"), file("b.psd")], directories: ["photos"] });
    const out = filesFromDrop(dt);
    expect(out.files.map((f) => f.name)).toEqual(["a.txt", "b.psd"]);
    expect(out.hadDirectory).toBe(true);
  });

  it("falls back to dt.files when items are unavailable", () => {
    const dt = { types: ["Files"], files: [file("only.txt")], items: undefined } as unknown as DataTransfer;
    expect(filesFromDrop(dt).files.map((f) => f.name)).toEqual(["only.txt"]);
  });
});

describe("dropOverflowMessage", () => {
  it("says how many were kept and how many left out", () => {
    expect(dropOverflowMessage(2, 1)).toBe("Only 2 more files could be attached; 1 was left out.");
    expect(dropOverflowMessage(1, 3)).toBe("Only 1 more file could be attached; 3 were left out.");
    expect(dropOverflowMessage(0, 2)).toMatch(/No more files/);
  });
});

/* ── the hook, through a minimal host component ── */

let host: HTMLDivElement;
let root: Root;
let received: File[][];
let rejected: string[];

function Host(props: Partial<UseFileDropOptions>) {
  const drop = useFileDrop({
    enabled: true,
    remainingSlots: 5,
    onFiles: (f) => received.push(f),
    onReject: (m) => rejected.push(m),
    ...props,
  });
  return (
    <section data-testid="pane" data-active={drop.active ? "1" : "0"} {...drop.handlers}>
      <div data-testid="child">child</div>
    </section>
  );
}

beforeEach(() => {
  received = [];
  rejected = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(props: Partial<UseFileDropOptions> = {}) {
  await act(async () => root.render(<Host {...props} />));
}

function fire(el: Element, type: string, dt: DataTransfer) {
  const ev = new Event(type, { bubbles: true, cancelable: true }) as Event & { dataTransfer?: DataTransfer };
  Object.defineProperty(ev, "dataTransfer", { value: dt });
  return act(async () => {
    el.dispatchEvent(ev);
  });
}

const pane = () => host.querySelector('[data-testid="pane"]')!;
const child = () => host.querySelector('[data-testid="child"]')!;
const active = () => pane().getAttribute("data-active") === "1";

describe("useFileDrop", () => {
  it("lights up while files hover, including across children, and goes dark on leave", async () => {
    await render();
    const dt = transfer({ files: [file("a.txt")] });
    await fire(pane(), "dragenter", dt);
    expect(active()).toBe(true);
    // Moving over a child fires enter then leave for the parent; the counter absorbs it.
    await fire(child(), "dragenter", dt);
    await fire(pane(), "dragleave", dt);
    expect(active()).toBe(true);
    await fire(child(), "dragleave", dt);
    expect(active()).toBe(false);
  });

  it("hands dropped files on and resets", async () => {
    await render();
    const dt = transfer({ files: [file("a.txt"), file("b.psd")] });
    await fire(pane(), "dragenter", dt);
    await fire(pane(), "drop", dt);
    expect(received).toEqual([[expect.objectContaining({ name: "a.txt" }), expect.objectContaining({ name: "b.psd" })]]);
    expect(rejected).toEqual([]);
    expect(active()).toBe(false);
  });

  it("ignores drags that carry no files, such as a sidebar chat or a link", async () => {
    await render();
    const dt = transfer({ types: ["text/plain"] });
    await fire(pane(), "dragenter", dt);
    expect(active()).toBe(false);
    await fire(pane(), "drop", dt);
    expect(received).toEqual([]);
  });

  it("does nothing when disabled", async () => {
    await render({ enabled: false });
    const dt = transfer({ files: [file("a.txt")] });
    await fire(pane(), "dragenter", dt);
    expect(active()).toBe(false);
    await fire(pane(), "drop", dt);
    expect(received).toEqual([]);
  });

  it("refuses a drop while a reply is streaming, with the reason", async () => {
    await render({ isBusy: () => true });
    const dt = transfer({ files: [file("a.txt")] });
    await fire(pane(), "drop", dt);
    expect(received).toEqual([]);
    expect(rejected).toEqual([DROP_BUSY_MESSAGE]);
  });

  it("rejects folders but still attaches the files beside them", async () => {
    await render();
    const dt = transfer({ files: [file("a.txt")], directories: ["photos"] });
    await fire(pane(), "drop", dt);
    expect(rejected).toEqual([DROP_DIRECTORY_MESSAGE]);
    expect(received[0].map((f) => f.name)).toEqual(["a.txt"]);
  });

  it("keeps only as many files as the message has room for and says so", async () => {
    await render({ remainingSlots: 2 });
    const dt = transfer({ files: [file("1.txt"), file("2.txt"), file("3.txt")] });
    await fire(pane(), "drop", dt);
    expect(received[0].map((f) => f.name)).toEqual(["1.txt", "2.txt"]);
    expect(rejected).toEqual([dropOverflowMessage(2, 1)]);
  });

  it("with no room left attaches nothing and explains", async () => {
    await render({ remainingSlots: 0 });
    await fire(pane(), "drop", transfer({ files: [file("1.txt")] }));
    expect(received).toEqual([]);
    expect(rejected[0]).toMatch(/No more files/);
  });
});

describe("the chat pane", () => {
  it("is wired to the hook and shows the overlay copy", () => {
    const sources = import.meta.glob("../components/ChatPanel.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const panel = sources["../components/ChatPanel.tsx"] ?? "";
    expect(panel).toContain("useFileDrop({");
    expect(panel).toContain("{...fileDrop.handlers}");
    expect(panel).toContain("Drop files to attach");
    expect(panel).toContain("enabled: !readOnly && !draggingSessionId");
    expect(panel).toContain("onFiles: (files) => void processPendingAttachmentFiles(files)");
  });
});
