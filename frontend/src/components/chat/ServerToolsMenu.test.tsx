/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ api: vi.fn(async () => []) }));

import { copyFreshChatTools } from "../../lib/chatTools";
import { resetChatToolPermissions, setPermittedChatTools } from "../../lib/chatToolPermissions";
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
});
