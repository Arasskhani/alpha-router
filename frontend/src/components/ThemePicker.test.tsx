/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ThemePicker from "./ThemePicker";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
});

async function render(value: Parameters<typeof ThemePicker>[0]["value"]) {
  const onChange = vi.fn();
  await act(async () => root.render(<ThemePicker value={value} onChange={onChange} />));
  return onChange;
}

describe("the theme picker", () => {
  it("offers ALPHA BLACK and chooses it", async () => {
    const onChange = await render("system");
    const select = host.querySelector<HTMLSelectElement>("select")!;
    expect([...select.options].map((o) => o.textContent)).toEqual(["Default", "Mint", "Dark Mint", "ALPHA BLACK", "ALPHA Neon", "Bloody Night"]);
    await act(async () => {
      select.value = "alpha-black";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith("alpha-black");
  });

  it("shows ALPHA BLACK as dark, and Light leaves it for the default light theme", async () => {
    const onChange = await render("alpha-black");
    expect(host.querySelector<HTMLSelectElement>("select")!.value).toBe("alpha-black");
    expect(host.querySelector('[aria-label="Dark"]')?.getAttribute("aria-pressed")).toBe("true");
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Light"]')!.click());
    expect(onChange).toHaveBeenCalledWith("light");
  });
});
