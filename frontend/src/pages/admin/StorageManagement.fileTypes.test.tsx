/**
 * @vitest-environment happy-dom
 *
 * The "File types" card on Storage Management. It keeps no draft: the mode is
 * saved as soon as it is confirmed, and each list opens in its own dialog
 * (tested in FileTypeListModal.test.tsx), so the card always shows what the
 * server enforces. The Block list applies in both modes; the Allow list only
 * in allowlist mode — the old card said otherwise.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
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
import {
  EXTENSION_PATTERN,
  diffLists,
  filterExtensions,
  isDefaultType,
  normalizeExtensionInput,
  normalizeSearchQuery,
} from "../../lib/fileTypePolicy";
import StorageManagement from "./StorageManagement";

describe("fileTypePolicy helpers", () => {
  it("normalises free text into sorted, deduplicated extensions", () => {
    expect(normalizeExtensionInput(" .PDF, exe\n pdf  Tar.gz,,DOCX ")).toEqual({
      valid: ["docx", "exe", "pdf"],
      invalid: ["tar.gz"],
    });
    expect(normalizeExtensionInput("")).toEqual({ valid: [], invalid: [] });
    expect(normalizeExtensionInput(". , .")).toEqual({ valid: [], invalid: [] });
  });

  it("accepts only 1–16 lowercase letters or digits", () => {
    expect(EXTENSION_PATTERN.test("mp4")).toBe(true);
    expect(EXTENSION_PATTERN.test("a".repeat(16))).toBe(true);
    expect(EXTENSION_PATTERN.test("a".repeat(17))).toBe(false);
    expect(EXTENSION_PATTERN.test("PDF")).toBe(false);
    expect(EXTENSION_PATTERN.test("tar.gz")).toBe(false);
    expect(EXTENSION_PATTERN.test("c++")).toBe(false);
    expect(normalizeExtensionInput("c++ x").invalid).toEqual(["c++"]);
  });

  it("diffs two lists as added and removed", () => {
    expect(diffLists(["exe", "html", "svg"], ["bat", "exe"])).toEqual({ added: ["bat"], removed: ["html", "svg"] });
    expect(diffLists(["a"], ["a"])).toEqual({ added: [], removed: [] });
  });

  it("knows which entries are shipped defaults", () => {
    expect(isDefaultType("exe", ["exe", "svg"])).toBe(true);
    expect(isDefaultType("pdf", ["exe", "svg"])).toBe(false);
  });

  it("searches by substring, ignoring case and a leading dot", () => {
    const list = ["docx", "exe", "htm", "html", "pdf"];
    expect(filterExtensions(list, "HT")).toEqual(["htm", "html"]);
    expect(filterExtensions(list, " .pd ")).toEqual(["pdf"]);
    expect(filterExtensions(list, "")).toEqual(list);
    expect(filterExtensions(list, "zip")).toEqual([]);
    expect(normalizeSearchQuery("  .PSD ")).toBe("psd");
  });
});

const FILE_TYPES = {
  mode: "blocklist" as "blocklist" | "allowlist",
  blocked: ["exe", "html", "svg"],
  allowed: ["docx", "pdf"],
  default_blocked: ["exe", "html", "svg"],
  default_allowed: ["docx", "pdf", "txt"],
};

const OVERVIEW = {
  total_files: 3,
  total_size_bytes: 1024,
  expired_files: 0,
  users_over_quota: 0,
  projects_over_quota: 0,
  by_kind: [],
  settings: {
    user_media_quota_gb: 1,
    user_media_quota_bytes: 1024 * 1024 * 1024,
    project_media_quota_gb: 1,
    project_media_quota_bytes: 1024 * 1024 * 1024,
    max_upload_file_mb: 25,
    max_chat_attachments_total_mb: 36,
    max_media_zip_download_mb: 256,
    max_chat_attachments_count: 5,
    max_code_interpreter_workspace_files: 5,
    max_code_interpreter_workspace_total_mb: 16,
  },
};

function answerWith(fileTypes: Partial<typeof FILE_TYPES> = {}) {
  const policy = { ...FILE_TYPES, ...fileTypes };
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/api/admin/storage") return { ...OVERVIEW, file_types: policy };
    if (path === "/api/admin/storage/file-type-policy" && init?.method === "PUT") {
      return { ok: true, file_types: { ...policy, ...JSON.parse(String(init.body)) } };
    }
    if (path === "/api/admin/storage/file-type-policy/reset") return { ok: true, file_types: FILE_TYPES };
    throw new Error(`unexpected ${path}`);
  });
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  confirmMock.mockReset();
  confirmMock.mockResolvedValue(true);
  readOnly.value = false;
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

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <StorageManagement />
      </MemoryRouter>,
    );
  });
}

function card(): HTMLElement {
  const el = host.querySelector<HTMLElement>("section.file-types-card");
  if (!el) throw new Error("File types card not rendered");
  return el;
}

function button(label: string, scope: ParentNode = document): HTMLButtonElement | undefined {
  return [...scope.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label);
}

/** A button whose text starts with `label` (the mode and list buttons carry a second line). */
function buttonStarting(label: string, scope: ParentNode = card()): HTMLButtonElement | undefined {
  return [...scope.querySelectorAll("button")].find((b) => (b.textContent || "").trim().startsWith(label));
}

function click(el: Element | undefined) {
  if (!el) throw new Error("element to click not found");
  return act(async () => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function calls(path: string, method?: string) {
  return vi
    .mocked(api)
    .mock.calls.filter((c) => c[0] === path && (method ? (c[1] as RequestInit)?.method === method : true));
}

function puts() {
  return calls("/api/admin/storage/file-type-policy", "PUT").map((c) => JSON.parse(String((c[1] as RequestInit).body)));
}

const modeButton = (label: string) => buttonStarting(label, card().querySelector(".file-types-mode")!);
const listButton = (label: "Block list" | "Allow list") =>
  buttonStarting(label, card().querySelector(".file-types-lists")!);
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]');
/** The card reports its own results: it sits far below the page-level banner. */
const note = () => card().querySelector(".file-types-note")?.textContent || "";
const searchBox = () => document.querySelector<HTMLInputElement>('input[aria-label="Search file types"]')!;

/** A promise the test settles by hand, to look at the page while a request is out. */
function deferred<T>() {
  let resolve: (v: T) => void = () => {};
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe("the File types card", () => {
  it("sits right after the transfer limits card", async () => {
    answerWith();
    await render();
    const cards = [...host.querySelectorAll("form.card, section.card")].map((c) => c.querySelector("h3")?.textContent);
    expect(cards.indexOf("File types")).toBe(cards.indexOf("Transfer size limits") + 1);
  });

  it("shows the saved mode and the size of each list, and no editor of its own", async () => {
    answerWith();
    await render();
    expect(modeButton("Block listed types")?.getAttribute("aria-pressed")).toBe("true");
    expect(modeButton("Allow only listed types")?.getAttribute("aria-pressed")).toBe("false");
    expect(listButton("Block list")?.textContent).toContain("3 types");
    expect(listButton("Allow list")?.textContent).toContain("2 types");
    expect(card().querySelector(".file-types-row, input, textarea")).toBeNull();
    expect(button("Save file type policy")).toBeUndefined();
    expect(card().textContent).not.toContain("Unsaved");
  });

  it("says the Block list is always in effect and the Allow list only in allowlist mode", async () => {
    answerWith();
    await render();
    expect(listButton("Block list")?.textContent).toContain("Always in effect");
    expect(listButton("Allow list")?.textContent).toContain("Not in effect in this mode");

    act(() => root.unmount());
    root = createRoot(host);
    answerWith({ mode: "allowlist" });
    await render();
    expect(modeButton("Allow only listed types")?.getAttribute("aria-pressed")).toBe("true");
    expect(listButton("Block list")?.textContent).toContain("Always in effect");
    expect(listButton("Allow list")?.textContent).toContain("In effect");
    expect(listButton("Allow list")?.textContent).not.toContain("Not in effect");
  });

  it("switches the mode only after a confirm, sending both lists back unchanged", async () => {
    answerWith();
    await render();
    await click(modeButton("Allow only listed types"));

    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0].title).toBe("Allow only the listed types?");
    expect(String(confirmMock.mock.calls[0][0].message)).toContain("2 types");
    expect(puts()).toEqual([{ mode: "allowlist", blocked: ["exe", "html", "svg"], allowed: ["docx", "pdf"] }]);
    expect(modeButton("Allow only listed types")?.getAttribute("aria-pressed")).toBe("true");
    expect(listButton("Allow list")?.textContent).not.toContain("Not in effect");
    expect(note()).toContain("Mode set to “Allow only listed types”");
    expect(note()).toContain("within two minutes");
    // Not repeated in the page-level banner above the first card.
    expect(host.querySelector(".admin-page > .alert-success")).toBeNull();
  });

  it("keeps the mode when the confirm is declined", async () => {
    confirmMock.mockResolvedValueOnce(false);
    answerWith();
    await render();
    await click(modeButton("Allow only listed types"));
    expect(puts()).toHaveLength(0);
    expect(modeButton("Block listed types")?.getAttribute("aria-pressed")).toBe("true");
  });

  it("does nothing when the mode already in force is clicked", async () => {
    answerWith();
    await render();
    await click(modeButton("Block listed types"));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(puts()).toHaveLength(0);
  });

  it("warns loudly before allowlist mode with an empty Allow list", async () => {
    confirmMock.mockResolvedValueOnce(false);
    answerWith({ allowed: [] });
    await render();
    await click(modeButton("Allow only listed types"));
    const opts = confirmMock.mock.calls[0][0];
    expect(opts.emphasize).toBe("every upload will be refused");
    expect(opts.danger).toBe(true);
    expect(puts()).toHaveLength(0);
  });

  it("asks before going back to blocklist mode too", async () => {
    answerWith({ mode: "allowlist" });
    await render();
    await click(modeButton("Block listed types"));
    expect(confirmMock.mock.calls[0][0].title).toBe("Block only the listed types?");
    expect(puts()).toEqual([{ mode: "blocklist", blocked: ["exe", "html", "svg"], allowed: ["docx", "pdf"] }]);
    expect(modeButton("Block listed types")?.getAttribute("aria-pressed")).toBe("true");
  });

  it("shows the server's reason on the card when a mode change is refused, and keeps the mode", async () => {
    answerWith();
    await render();
    vi.mocked(api).mockRejectedValueOnce(new Error("Forbidden"));
    await click(modeButton("Allow only listed types"));
    expect(note()).toBe("The mode was not changed: Forbidden");
    expect(card().querySelector(".file-types-note .alert-error")).not.toBeNull();
    expect(modeButton("Block listed types")?.getAttribute("aria-pressed")).toBe("true");
  });

  it("allows one change at a time while a save is out", async () => {
    answerWith();
    await render();
    const pending = deferred<unknown>();
    vi.mocked(api).mockImplementationOnce(() => pending.promise as Promise<never>);
    await click(modeButton("Allow only listed types"));

    expect(modeButton("Block listed types")?.disabled).toBe(true);
    expect(button("Restore defaults", card())?.disabled).toBe(true);
    expect(listButton("Block list")?.disabled).toBe(true);
    expect(listButton("Allow list")?.disabled).toBe(true);

    await act(async () => pending.resolve({ ok: true, file_types: { ...FILE_TYPES, mode: "allowlist" } }));
    expect(button("Restore defaults", card())?.disabled).toBe(false);
    expect(listButton("Block list")?.disabled).toBe(false);
  });

  it("opens each list in its own dialog", async () => {
    answerWith();
    await render();
    expect(dialog()).toBeNull();

    await click(listButton("Block list"));
    expect(dialog()?.getAttribute("aria-label")).toBe("Block list");
    expect(dialog()?.textContent).toContain(".exe");
    await click(button("Cancel", dialog()!));
    expect(dialog()).toBeNull();

    await click(listButton("Allow list"));
    expect(dialog()?.getAttribute("aria-label")).toBe("Allow list");
    expect(dialog()?.textContent).toContain(".docx");
    expect(dialog()?.textContent).toContain("Not in effect");
  });

  it("updates the card from a save in the dialog without reloading the page", async () => {
    answerWith();
    await render();
    expect(calls("/api/admin/storage")).toHaveLength(1);

    await click(listButton("Block list"));
    await type(searchBox(), "bat");
    await click(button("Add .bat to the Block list"));
    await click(button("Save", dialog()!));

    expect(puts()).toEqual([{ mode: "blocklist", blocked: ["bat", "exe", "html", "svg"], allowed: ["docx", "pdf"] }]);
    expect(dialog()).toBeNull();
    expect(listButton("Block list")?.textContent).toContain("4 types");
    expect(note()).toContain("Block list saved (+1 −0)");
    expect(note()).toContain("within two minutes");
    expect(calls("/api/admin/storage")).toHaveLength(1);
  });

  it("says when an Allow list saved in blocklist mode will take effect", async () => {
    answerWith();
    await render();
    await click(listButton("Allow list"));
    await type(searchBox(), "txt");
    await click(button("Add .txt to the Allow list"));
    await click(button("Save", dialog()!));
    expect(listButton("Allow list")?.textContent).toContain("3 types");
    expect(note()).toContain("It takes effect when the mode is “Allow only listed types”.");
  });

  it("restores defaults through the reset endpoint after a confirm", async () => {
    answerWith({ mode: "allowlist", blocked: ["exe"] });
    await render();
    await click(button("Restore defaults", card()));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    const reset = calls("/api/admin/storage/file-type-policy/reset");
    expect(reset).toHaveLength(1);
    expect((reset[0][1] as RequestInit).method).toBe("POST");
    expect(note()).toContain("back to the defaults");
    expect(modeButton("Block listed types")?.getAttribute("aria-pressed")).toBe("true");
    expect(listButton("Block list")?.textContent).toContain("3 types");
  });

  it("does not reset when the confirm is declined", async () => {
    confirmMock.mockResolvedValueOnce(false);
    answerWith();
    await render();
    await click(button("Restore defaults", card()));
    expect(calls("/api/admin/storage/file-type-policy/reset")).toHaveLength(0);
  });

  it("lets a read-only admin open and search both lists but change nothing", async () => {
    readOnly.value = true;
    answerWith();
    await render();
    expect(modeButton("Block listed types")?.disabled).toBe(true);
    expect(modeButton("Allow only listed types")?.disabled).toBe(true);
    expect(button("Restore defaults", card())?.disabled).toBe(true);
    // Readable despite the read-only lock that greys out buttons on admin forms.
    expect(listButton("Block list")?.disabled).toBe(false);
    expect(listButton("Block list")?.className).toContain("btn-readonly-ok");

    await click(listButton("Block list"));
    expect(button("Save", dialog()!)?.disabled).toBe(true);
    await type(searchBox(), "ht");
    expect(dialog()?.textContent).toContain("1 match for “ht”");
    await click(button("Close", dialog()!));
    expect(dialog()).toBeNull();

    await click(listButton("Allow list"));
    expect(dialog()?.getAttribute("aria-label")).toBe("Allow list");
    await type(searchBox(), "pd");
    expect(dialog()?.textContent).toContain(".pdf");
    expect(dialog()?.textContent).not.toContain(".docx");
    expect(button("Add file type", dialog()!)?.disabled).toBe(true);
  });

  it("explains when the server reports no file type policy", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/admin/storage") return { ...OVERVIEW };
      throw new Error(`unexpected ${path}`);
    });
    await render();
    expect(card().textContent).toContain("This server does not report a file type policy.");
    expect(card().querySelector(".file-types-lists")).toBeNull();
  });
});
