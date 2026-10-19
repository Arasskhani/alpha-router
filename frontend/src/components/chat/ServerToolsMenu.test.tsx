/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn(async () => []) }));

import { copyFreshChatTools } from "../../lib/chatTools";
import { loadChatToolPermissions, resetChatToolPermissions, setPermittedChatTools } from "../../lib/chatToolPermissions";
import { api } from "../../api";
import ServerToolsMenu from "./ServerToolsMenu";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
  resetChatToolPermissions();
});

function open() {
  const anchor = document.createElement("button");
  document.body.appendChild(anchor);
  act(() => {
    root.render(
      <ServerToolsMenu
        open
        anchorRef={{ current: anchor }}
        tools={copyFreshChatTools()}
        privateMode={false}
        onChange={() => {}}
        onPrivateModeChange={() => {}}
        onClose={() => {}}
      />,
    );
  });
}

/** Tool rows are the only elements carrying this class. */
function visibleTools(): string[] {
  return [...document.querySelectorAll(".alpha-router-server-tool strong")].map(
    (el) => el.textContent || "",
  );
}

describe("the chat tools menu", () => {
  it("shows every tool while the verdicts are unknown", () => {
    open();
    expect(visibleTools()).toContain("Web Search");
    expect(visibleTools()).toContain("Code Interpreter");
  });

  it("leaves out a tool this account has not been given", () => {
    setPermittedChatTools([
      "web_search",
      "web_fetch",
      "image_generation",
      "video_generation",
      "speech_generation",
      "private_mode",
    ]);
    open();
    expect(visibleTools()).toContain("Web Search");
    expect(visibleTools()).not.toContain("Code Interpreter");
  });

  it("can leave out Private Mode too", () => {
    setPermittedChatTools(["web_search"]);
    open();
    expect(visibleTools()).toEqual(["Web Search"]);
  });

  it("shows Web Search off, saying why, when there is no search service", async () => {
    vi.mocked(api).mockResolvedValueOnce([
      { key: "web_search", title: "Web Search", description: "", icon: "globe", permitted: true, available: false, unavailable_reason: "No web search service is set up." },
      { key: "web_fetch", title: "Web Fetch", description: "", icon: "link", permitted: true, available: true },
    ]);
    await loadChatToolPermissions();
    open();
    const row = [...document.querySelectorAll(".alpha-router-server-tool")].find((el) => el.textContent?.includes("Web Search"))!;
    expect(row.textContent).toContain("No web search service is set up.");
    expect(row.querySelector("button")!.disabled).toBe(true);
    expect(row.querySelector("button")!.getAttribute("aria-pressed")).toBe("false");
  });
});
