/**
 * @vitest-environment happy-dom
 *
 * One upload file-type list in its own dialog: search it, add to it, take
 * entries off it, and save — with nothing sent until Save, a confirmation
 * before anything is unblocked, and the draft kept when the server says no.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));
const confirmMock = vi.hoisted(() => vi.fn(async (_opts: Record<string, unknown>): Promise<boolean> => true));

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: confirmMock, prompt: vi.fn() }),
}));

import { api } from "../../api";
import type { FileTypeListKey, FileTypePolicy } from "../../lib/fileTypePolicy";
import FileTypeListModal from "./FileTypeListModal";

const POLICY: FileTypePolicy = {
  mode: "blocklist",
  blocked: ["exe", "html", "svg"],
  allowed: ["docx", "pdf"],
  default_blocked: ["exe", "html", "svg"],
  default_allowed: ["docx", "pdf", "txt"],
};

let host: HTMLDivElement;
let root: Root;
let onClose: ReturnType<typeof vi.fn>;
let onSaved: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (_path: string, init?: RequestInit) => ({
    ok: true,
    file_types: { ...POLICY, ...JSON.parse(String(init?.body ?? "{}")) },
  }));
  confirmMock.mockReset();
  confirmMock.mockResolvedValue(true);
  readOnly.value = false;
  onClose = vi.fn();
  onSaved = vi.fn();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
  document.body.style.overflow = "";
});

async function open(listKey: FileTypeListKey = "blocked", policy: Partial<FileTypePolicy> = {}) {
  await act(async () => {
    root.render(
      <FileTypeListModal
        listKey={listKey}
        policy={{ ...POLICY, ...policy }}
        onClose={onClose as () => void}
        onSaved={onSaved as (p: FileTypePolicy, c: { added: string[]; removed: string[] }) => void}
      />,
    );
  });
}

function dialog(): HTMLElement {
  const el = document.querySelector<HTMLElement>('[role="dialog"]');
  if (!el) throw new Error("dialog not rendered");
  return el;
}

function rows(): string[] {
  return [...document.querySelectorAll(".file-types-row .file-types-row__name")].map((n) => n.textContent || "");
}

function row(ext: string): HTMLElement {
  const el = [...document.querySelectorAll<HTMLElement>(".file-types-row")].find(
    (li) => li.querySelector(".file-types-row__name")?.textContent === `.${ext}`,
  );
  if (!el) throw new Error(`row .${ext} not rendered`);
  return el;
}

function tags(ext: string): string[] {
  return [...row(ext).querySelectorAll(".file-types-tag")].map((t) => t.textContent || "");
}

function button(label: string, scope: ParentNode = document): HTMLButtonElement | undefined {
  return [...scope.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label);
}

function labelled(name: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === name);
}

function click(el: Element | undefined) {
  if (!el) throw new Error("element to click not found");
  return act(async () => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

/** React tracks the value itself; a plain assignment does not reach onChange. */
function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function press(target: EventTarget, key: string) {
  return act(async () => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

const search = () => document.querySelector<HTMLInputElement>('input[aria-label="Search file types"]')!;
const addInput = () => document.getElementById("file-types-add-input") as HTMLInputElement | null;
const status = () => document.querySelector(".file-types-modal__status")?.textContent || "";

function puts() {
  return vi
    .mocked(api)
    .mock.calls.filter((c) => c[0] === "/api/admin/storage/file-type-policy" && (c[1] as RequestInit)?.method === "PUT")
    .map((c) => JSON.parse(String((c[1] as RequestInit).body)));
}

describe("the file type list dialog", () => {
  it("opens as a dialog named after its list, with the search box focused", async () => {
    await open();
    expect(dialog().getAttribute("aria-label")).toBe("Block list");
    expect(document.activeElement).toBe(search());
  });

  it("lists the saved entries sorted, tagging the ones an administrator added", async () => {
    await open("blocked", { blocked: ["svg", "exe", "zzz", "html"] });
    expect(rows()).toEqual([".exe", ".html", ".svg", ".zzz"]);
    // The shipped defaults are most of every list; only the exceptions carry a tag.
    expect(tags("exe")).toEqual([]);
    expect(tags("zzz")).toEqual(["custom"]);
    expect(dialog().textContent).toContain("4 types · 1 custom");
    expect(status()).toBe("No unsaved changes");
  });

  it("searches without regard to case or a leading dot", async () => {
    await open();
    await type(search(), ".HT");
    expect(rows()).toEqual([".html"]);
    expect(dialog().textContent).toContain("1 match for “ht”");
    await type(search(), "");
    expect(rows()).toEqual([".exe", ".html", ".svg"]);
  });

  it("offers to add a searched type that is not on the list", async () => {
    await open();
    await type(search(), "PSD");
    expect(rows()).toEqual([]);
    expect(dialog().textContent).toContain("No matches for “psd”");

    await click(button("Add .psd to the Block list"));
    expect(rows()).toEqual([".psd"]);
    expect(tags("psd")).toEqual(["new"]);
    expect(status()).toBe("Unsaved: +1 −0");
    expect(puts()).toHaveLength(0);
  });

  it("still offers to add the exact type when the search only matches others", async () => {
    await open("blocked", { blocked: ["exe", "html", "svg", "htmx"] });
    await type(search(), "htm");
    expect(rows()).toEqual([".html", ".htmx"]);
    await click(button("Add .htm to the Block list"));
    expect(rows()).toEqual([".htm", ".html", ".htmx"]);
    expect(tags("htm")).toEqual(["new"]);
  });

  it("offers no shortcut for an invalid search or one already listed", async () => {
    await open();
    await type(search(), "tar.gz");
    expect(dialog().querySelector(".file-types-modal__shortcut")).toBeNull();
    await type(search(), "exe");
    expect(dialog().querySelector(".file-types-modal__shortcut")).toBeNull();
  });

  it("lets Escape empty the search first, and close the dialog only after that", async () => {
    await open();
    await type(search(), "ex");
    await press(search(), "Escape");
    expect(search().value).toBe("");
    expect(onClose).not.toHaveBeenCalled();

    await press(search(), "Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("adds several types at once from the Add row, previewing each", async () => {
    await open();
    expect(addInput()).toBeNull();
    await click(button("Add file type"));
    expect(document.activeElement).toBe(addInput());

    await type(addInput()!, ".PSD, exe tar.gz");
    const items = [...document.querySelectorAll(".file-types-add-preview li")].map((li) => ({
      text: (li.textContent || "").replace(/\s+/g, " ").trim(),
      cls: li.className,
    }));
    expect(items).toEqual([
      { text: "psd ✓", cls: expect.stringContaining("is-ok") },
      { text: "exe already listed", cls: expect.stringContaining("is-listed") },
      { text: "tar.gz invalid", cls: expect.stringContaining("is-invalid") },
    ]);

    await click(button("Add 1 type"));
    expect(addInput()).toBeNull();
    expect(rows()).toEqual([".exe", ".html", ".psd", ".svg"]);
    expect(tags("psd")).toEqual(["new"]);
    expect(document.activeElement).toBe(button("Add file type"));
    expect(puts()).toHaveLength(0);
  });

  it("keeps a pasted column apart instead of letting the input glue it into one word", async () => {
    await open();
    await click(button("Add file type"));
    const input = addInput()!;
    const paste = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(paste, "clipboardData", { value: { getData: () => "psd\r\ndwg\n\nparquet\n" } });
    await act(async () => {
      input.dispatchEvent(paste);
    });
    expect(paste.defaultPrevented).toBe(true);
    expect(addInput()!.value).toBe("psd, dwg, parquet");
    expect(button("Add 3 types")?.disabled).toBe(false);
  });

  it("keeps Add disabled until something new and valid is typed", async () => {
    await open();
    await click(button("Add file type"));
    await type(addInput()!, "exe, tar.gz");
    expect(button("Add 0 types")?.disabled).toBe(true);
  });

  it("closes the Add row on Escape without closing the dialog", async () => {
    await open();
    await click(button("Add file type"));
    await type(addInput()!, "psd");
    await press(addInput()!, "Escape");
    expect(addInput()).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(rows()).toEqual([".exe", ".html", ".svg"]);
  });

  it("strikes a removed entry through until Save, and Undo brings it back", async () => {
    await open();
    await click(labelled("Remove .svg"));
    expect(row("svg").className).toContain("is-removed");
    expect(tags("svg")).toEqual(["removed"]);
    expect(status()).toBe("Unsaved: +0 −1");

    await click(labelled("Undo removing .svg"));
    expect(row("svg").className).toContain("is-kept");
    expect(status()).toBe("No unsaved changes");
  });

  it("drops a new, unsaved entry outright when it is removed", async () => {
    await open();
    await type(search(), "psd");
    await click(button("Add .psd to the Block list"));
    await click(labelled("Remove .psd"));
    expect(rows()).toEqual([]);
    expect(status()).toBe("No unsaved changes");
  });

  it("resets the draft to the shipped defaults without saving", async () => {
    await open("blocked", { blocked: ["exe", "zzz"] });
    await click(button("Reset this list to defaults"));
    expect(rows()).toEqual([".exe", ".html", ".svg", ".zzz"]);
    expect(row("html").className).toContain("is-new");
    expect(row("zzz").className).toContain("is-removed");
    expect(status()).toBe("Unsaved: +2 −1");
    expect(button("Reset this list to defaults")?.disabled).toBe(true);
    expect(puts()).toHaveLength(0);
  });

  it("saves with PUT, sending the saved mode and the other list unchanged", async () => {
    await open();
    await type(search(), "bat");
    await click(button("Add .bat to the Block list"));
    await click(button("Save"));

    expect(confirmMock).not.toHaveBeenCalled();
    expect(puts()).toEqual([{ mode: "blocklist", blocked: ["bat", "exe", "html", "svg"], allowed: ["docx", "pdf"] }]);
    expect(onSaved).toHaveBeenCalledTimes(1);
    const [policy, changes] = onSaved.mock.calls[0];
    expect(policy.blocked).toEqual(["bat", "exe", "html", "svg"]);
    expect(changes).toEqual({ added: ["bat"], removed: [] });
  });

  it("saves the Allow list the same way, leaving the Block list alone", async () => {
    await open("allowed", { mode: "allowlist" });
    await type(search(), "txt");
    await click(button("Add .txt to the Allow list"));
    await click(button("Save"));
    expect(puts()).toEqual([{ mode: "allowlist", blocked: ["exe", "html", "svg"], allowed: ["docx", "pdf", "txt"] }]);
  });

  it("asks before a save that unblocks anything, and names what it unblocks", async () => {
    await open();
    await click(labelled("Remove .exe"));
    await click(button("Save"));

    expect(confirmMock).toHaveBeenCalledTimes(1);
    const opts = confirmMock.mock.calls[0][0];
    expect(opts.title).toBe("Unblock 1 file type?");
    expect(String(opts.message)).toContain(".exe");
    expect(opts.danger).toBe(true);
    expect(puts()).toEqual([{ mode: "blocklist", blocked: ["html", "svg"], allowed: ["docx", "pdf"] }]);
  });

  it("does not save when the unblock is declined, and keeps the draft", async () => {
    confirmMock.mockResolvedValueOnce(false);
    await open();
    await click(labelled("Remove .exe"));
    await click(button("Save"));
    expect(puts()).toHaveLength(0);
    expect(onSaved).not.toHaveBeenCalled();
    expect(row("exe").className).toContain("is-removed");
  });

  it("warns before an empty Allow list is saved in allowlist mode", async () => {
    confirmMock.mockResolvedValueOnce(false);
    await open("allowed", { mode: "allowlist" });
    await click(labelled("Remove .docx"));
    await click(labelled("Remove .pdf"));
    await click(button("Save"));

    expect(confirmMock).toHaveBeenCalledTimes(1);
    const opts = confirmMock.mock.calls[0][0];
    expect(opts.emphasize).toBe("every upload will be refused");
    expect(opts.danger).toBe(true);
    expect(puts()).toHaveLength(0);
  });

  it("does not warn about an empty Allow list when the mode is not allowlist", async () => {
    await open("allowed");
    await click(labelled("Remove .docx"));
    await click(labelled("Remove .pdf"));
    await click(button("Save"));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(puts()).toEqual([{ mode: "blocklist", blocked: ["exe", "html", "svg"], allowed: [] }]);
  });

  it("shows a refused save inside the dialog and keeps the draft", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Not a file extension: 'x'"));
    await open();
    await type(search(), "bat");
    await click(button("Add .bat to the Block list"));
    await click(button("Save"));

    expect(dialog().querySelector('[role="alert"]')?.textContent).toContain("Not a file extension");
    expect(onSaved).not.toHaveBeenCalled();
    expect(tags("bat")).toEqual(["new"]);
    expect(button("Save")?.disabled).toBe(false);
  });

  it("holds every control that could change the draft while a save is out", async () => {
    let finish: (v: unknown) => void = () => {};
    vi.mocked(api).mockImplementationOnce(
      () => new Promise<unknown>((resolve) => (finish = resolve)) as Promise<never>,
    );
    await open();
    await type(search(), "bat");
    await click(button("Add .bat to the Block list"));
    await type(search(), "");
    await click(button("Save"));

    expect(button("Saving…")?.disabled).toBe(true);
    expect(button("Add file type")?.disabled).toBe(true);
    expect(button("Cancel")?.disabled).toBe(true);
    for (const b of document.querySelectorAll<HTMLButtonElement>(".file-types-row__remove")) {
      expect(b.disabled).toBe(true);
    }
    // Nothing typed into the search can be added while the save is out either.
    await type(search(), "psd");
    expect(button("Add .psd to the Block list")?.disabled).toBe(true);

    await act(async () => finish({ ok: true, file_types: { ...POLICY, blocked: ["bat", "exe", "html", "svg"] } }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved.mock.calls[0][1]).toEqual({ added: ["bat"], removed: [] });
  });

  it("ignores its own controls while one of its confirmations is open", async () => {
    let answer: (v: boolean) => void = () => {};
    confirmMock.mockImplementationOnce(() => new Promise<boolean>((resolve) => (answer = resolve)));
    await open();
    await click(labelled("Remove .exe"));
    await click(button("Save"));
    expect(confirmMock).toHaveBeenCalledTimes(1);

    // Tab can carry focus out of a confirmation and back into this dialog.
    await click(button("Save"));
    await click(labelled("Remove .svg"));
    await click(labelled("Undo removing .exe"));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(puts()).toHaveLength(0);
    expect(row("svg").className).toContain("is-kept");
    expect(row("exe").className).toContain("is-removed");

    await act(async () => answer(false));
    expect(puts()).toHaveLength(0);
    expect(labelled("Remove .svg")?.disabled).toBe(false);
  });

  it("puts focus back where it was once a confirmation is answered", async () => {
    // The real confirmation takes focus when it opens and drops it when it closes.
    confirmMock.mockImplementationOnce(async () => {
      (document.activeElement as HTMLElement | null)?.blur();
      return false;
    });
    await open();
    await click(labelled("Remove .svg"));
    const cancel = button("Cancel")!;
    cancel.focus();
    await click(cancel);
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(cancel);
  });

  it("falls back to what it sent when the server answers without the policy", async () => {
    vi.mocked(api).mockResolvedValueOnce({ ok: true });
    await open();
    await type(search(), "bat");
    await click(button("Add .bat to the Block list"));
    await click(button("Save"));
    const [policy] = onSaved.mock.calls[0];
    expect(policy).toEqual({ ...POLICY, blocked: ["bat", "exe", "html", "svg"] });
  });

  it("closes at once when nothing has changed", async () => {
    await open();
    await click(button("Cancel"));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("asks before discarding changes, and stays open when told to", async () => {
    confirmMock.mockResolvedValueOnce(false);
    await open();
    await click(labelled("Remove .svg"));
    await click(button("Cancel"));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0].title).toBe("Discard your changes?");
    expect(onClose).not.toHaveBeenCalled();

    await click(button("Cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to its own confirmation while one is open", async () => {
    let answer: (v: boolean) => void = () => {};
    confirmMock.mockImplementationOnce(() => new Promise<boolean>((resolve) => (answer = resolve)));
    await open();
    await click(labelled("Remove .svg"));
    await click(button("Cancel"));
    expect(confirmMock).toHaveBeenCalledTimes(1);

    // The confirmation is showing; an Escape now must not ask again or close.
    await press(window, "Escape");
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => answer(false));
    expect(onClose).not.toHaveBeenCalled();
    await press(window, "Escape");
    expect(confirmMock).toHaveBeenCalledTimes(2);
  });

  it("marks Allow list entries that the Block list still refuses, and says when the list is not in effect", async () => {
    await open("allowed", { blocked: ["exe", "pdf"] });
    expect(dialog().querySelector(".file-types-modal__notice")?.textContent).toContain("Not in effect");
    expect(tags("pdf")).toEqual(["still blocked"]);
    expect(tags("docx")).toEqual([]);

    await click(button("Add file type"));
    await type(addInput()!, "exe");
    expect(document.querySelector(".file-types-add-preview")?.textContent).toContain("on the Block list, still refused");
  });

  it("has no not-in-effect notice on the Allow list in allowlist mode, nor on the Block list", async () => {
    await open("allowed", { mode: "allowlist" });
    expect(dialog().querySelector(".file-types-modal__notice")).toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    await open("blocked");
    expect(dialog().querySelector(".file-types-modal__notice")).toBeNull();
  });

  it("lets a read-only administrator search the list but change nothing", async () => {
    readOnly.value = true;
    await open();
    expect(button("Add file type")?.disabled).toBe(true);
    expect(button("Save")?.disabled).toBe(true);
    expect(button("Reset this list to defaults")?.disabled).toBe(true);
    for (const remove of document.querySelectorAll<HTMLButtonElement>(".file-types-row__remove")) {
      expect(remove.disabled).toBe(true);
    }
    expect(status()).toContain("Read-only");

    await type(search(), "psd");
    expect(dialog().querySelector(".file-types-modal__shortcut")).toBeNull();
    expect(dialog().textContent).toContain("Nothing on this list matches “psd”.");
    await type(search(), "ht");
    expect(rows()).toEqual([".html"]);

    const close = button("Close");
    expect(close?.disabled).toBe(false);
    await click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("will not send a list longer than the server accepts", async () => {
    const full = Array.from({ length: 500 }, (_, i) => `t${i}`);
    await open("blocked", { blocked: full });
    await type(search(), "extra");
    await click(button("Add .extra to the Block list"));
    expect(dialog().querySelector(".file-types-modal__cap")?.textContent).toContain("at most 500");
    expect(button("Save")?.disabled).toBe(true);
  });
});
