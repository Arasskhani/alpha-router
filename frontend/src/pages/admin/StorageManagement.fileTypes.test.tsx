/**
 * @vitest-environment happy-dom
 *
 * The "File types" card on Storage Management: two modes, an editable chip
 * list where every default can go, a popup for adding several extensions at
 * once, and a Save that sends exactly the draft the operator was looking at.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));
const confirmMock = vi.hoisted(() => vi.fn(async () => true));

vi.mock("../../api", () => ({ api: vi.fn(), formatApiError: (e: unknown) => String(e) }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: confirmMock, prompt: vi.fn() }),
}));

import { api } from "../../api";
import { EXTENSION_PATTERN, diffLists, isDefaultType, normalizeExtensionInput } from "../../lib/fileTypePolicy";
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
    expect(normalizeExtensionInput("c++ x".repeat(1)).invalid).toEqual(["c++"]);
  });

  it("diffs two lists as added and removed", () => {
    expect(diffLists(["exe", "html", "svg"], ["bat", "exe"])).toEqual({ added: ["bat"], removed: ["html", "svg"] });
    expect(diffLists(["a"], ["a"])).toEqual({ added: [], removed: [] });
  });

  it("knows which entries are shipped defaults", () => {
    expect(isDefaultType("exe", ["exe", "svg"])).toBe(true);
    expect(isDefaultType("pdf", ["exe", "svg"])).toBe(false);
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
  confirmMock.mockClear();
  readOnly.value = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
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
  const el = host.querySelector<HTMLElement>('form[aria-label="File types"]');
  if (!el) throw new Error("File types card not rendered");
  return el;
}

function chips(scope: ParentNode = card()): string[] {
  return [...scope.querySelectorAll(".file-types-chip .file-types-chip__name")].map((n) => n.textContent || "");
}

function button(label: string, scope: ParentNode = document): HTMLButtonElement | undefined {
  return [...scope.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label);
}

function click(el: Element | undefined) {
  if (!el) throw new Error("element to click not found");
  return act(async () => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

/** React tracks the value itself; a plain assignment does not reach onChange. */
function setValue(el: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function putCalls() {
  return vi
    .mocked(api)
    .mock.calls.filter((c) => c[0] === "/api/admin/storage/file-type-policy" && (c[1] as RequestInit)?.method === "PUT")
    .map((c) => JSON.parse(String((c[1] as RequestInit).body)));
}

describe("the File types card", () => {
  it("sits right after the transfer limits card", async () => {
    answerWith();
    await render();
    const forms = [...host.querySelectorAll("form.card")].map((f) => f.querySelector("h3")?.textContent);
    expect(forms.indexOf("File types")).toBe(forms.indexOf("Transfer size limits") + 1);
  });

  it("renders the active list sorted, tagging shipped defaults", async () => {
    answerWith({ blocked: ["svg", "exe", "zzz", "html"] });
    await render();
    expect(chips()).toEqual(["exe", "html", "svg", "zzz"]);
    const tagged = [...card().querySelectorAll(".file-types-chip")]
      .filter((c) => c.querySelector(".file-types-chip__default"))
      .map((c) => c.querySelector(".file-types-chip__name")?.textContent);
    expect(tagged).toEqual(["exe", "html", "svg"]);
    expect(card().textContent).toContain("4 types");
    expect(card().textContent).not.toContain("Unsaved changes");
  });

  it("lets a default chip be removed and marks the draft dirty", async () => {
    answerWith();
    await render();
    await click(card().querySelector('button[aria-label="Remove svg"]') ?? undefined);
    expect(chips()).toEqual(["exe", "html"]);
    expect(card().textContent).toContain("Unsaved changes");
    expect(putCalls()).toHaveLength(0);
  });

  it("opens Add file type in a dialog rather than inline", async () => {
    answerWith();
    await render();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.getElementById("file-types-add-input")).toBeNull();

    await click(button("Add file type", card()));
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog?.getAttribute("aria-label")).toContain("Add file type");
    expect(dialog?.querySelector("#file-types-add-input")).not.toBeNull();
  });

  it("previews each parsed entry and adds only the valid, unlisted ones", async () => {
    answerWith();
    await render();
    await click(button("Add file type", card()));
    const input = document.getElementById("file-types-add-input") as HTMLTextAreaElement;
    await setValue(input, ".PDF, exe tar.gz");

    const preview = document.querySelector(".file-types-add-preview");
    const items = [...(preview?.querySelectorAll("li") ?? [])].map((li) => ({
      text: (li.textContent || "").replace(/\s+/g, " ").trim(),
      cls: li.className,
    }));
    expect(items).toEqual([
      { text: "pdf ✓", cls: expect.stringContaining("is-ok") },
      { text: "exe already listed", cls: expect.stringContaining("is-listed") },
      { text: "tar.gz invalid", cls: expect.stringContaining("is-invalid") },
    ]);

    const add = button("Add 1 type");
    expect(add?.disabled).toBe(false);
    await click(add);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(chips()).toEqual(["exe", "html", "pdf", "svg"]);
    expect(putCalls()).toHaveLength(0);
  });

  it("disables Add when nothing valid was typed", async () => {
    answerWith();
    await render();
    await click(button("Add file type", card()));
    const input = document.getElementById("file-types-add-input") as HTMLTextAreaElement;
    await setValue(input, "exe, tar.gz");
    expect(button("Add 0 types")?.disabled).toBe(true);
  });

  it("saves the full draft with PUT and reports success", async () => {
    answerWith();
    await render();
    await click(card().querySelector('button[aria-label="Remove html"]') ?? undefined);
    await click(button("Add file type", card()));
    await setValue(document.getElementById("file-types-add-input") as HTMLTextAreaElement, "bat");
    await click(button("Add 1 type"));
    await click(button("Save file type policy"));

    expect(putCalls()).toEqual([{ mode: "blocklist", blocked: ["bat", "exe", "svg"], allowed: ["docx", "pdf"] }]);
    expect(host.querySelector(".alert-success")?.textContent).toContain("File type policy saved");
  });

  it("shows the server's detail when a save is refused", async () => {
    answerWith();
    await render();
    vi.mocked(api).mockRejectedValueOnce(new Error("Invalid extension: tar.gz"));
    await click(card().querySelector('button[aria-label="Remove svg"]') ?? undefined);
    await click(button("Save file type policy"));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Invalid extension: tar.gz");
  });

  it("switches which list the chips show when the mode changes, without saving", async () => {
    answerWith();
    await render();
    const allowRadio = card().querySelector<HTMLInputElement>('input[value="allowlist"]');
    await click(allowRadio ?? undefined);
    expect(allowRadio?.checked).toBe(true);
    expect(chips()).toEqual(["docx", "pdf"]);
    expect(card().textContent).toContain("Allowed types");
    expect(card().textContent).toContain("Unsaved changes");
    expect(putCalls()).toHaveLength(0);

    await click(button("Save file type policy"));
    expect(putCalls()).toEqual([{ mode: "allowlist", blocked: ["exe", "html", "svg"], allowed: ["docx", "pdf"] }]);
  });

  it("shows the inactive list read-only on request", async () => {
    answerWith();
    await render();
    expect(card().textContent).not.toContain("docx");
    await click(button("Show the allowlist too", card()));
    const other = card().querySelector(".file-types-other");
    expect(chips(other!)).toEqual(["docx", "pdf"]);
    expect(other?.querySelector(".file-types-chip__remove")).toBeNull();
    await click(button("Hide the allowlist", card()));
    expect(card().querySelector(".file-types-other")).toBeNull();
  });

  it("restores defaults through the reset endpoint after a confirm", async () => {
    answerWith();
    await render();
    await click(button("Restore defaults"));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    const reset = vi.mocked(api).mock.calls.filter((c) => c[0] === "/api/admin/storage/file-type-policy/reset");
    expect(reset).toHaveLength(1);
    expect((reset[0][1] as RequestInit).method).toBe("POST");
    expect(host.querySelector(".alert-success")?.textContent).toContain("restored to defaults");
  });

  it("does not reset when the confirm is declined", async () => {
    answerWith();
    confirmMock.mockResolvedValueOnce(false);
    await render();
    await click(button("Restore defaults"));
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).not.toContain("/api/admin/storage/file-type-policy/reset");
  });

  it("shows the lists to a read-only admin but disables every mutating control", async () => {
    readOnly.value = true;
    answerWith();
    await render();
    expect(chips()).toEqual(["exe", "html", "svg"]);
    expect(button("Save file type policy")?.disabled).toBe(true);
    expect(button("Add file type", card())?.disabled).toBe(true);
    expect(button("Restore defaults")?.disabled).toBe(true);
    for (const remove of card().querySelectorAll<HTMLButtonElement>(".file-types-chip__remove")) {
      expect(remove.disabled).toBe(true);
    }
    for (const radio of card().querySelectorAll<HTMLInputElement>('input[type="radio"]')) {
      expect(radio.disabled).toBe(true);
    }
  });
});
