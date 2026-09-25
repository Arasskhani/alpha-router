/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import PanelMarkdown from "./PanelMarkdown";

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

async function render(text: string) {
  await act(async () => root.render(<PanelMarkdown text={text} />));
}

describe("answers in the panel", () => {
  it("open links in a new tab, without an opener", async () => {
    await render("See [the docs](https://example.com/docs).");
    const link = host.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://example.com/docs");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it.each(["javascript:alert(1)", "data:text/html,<script>x</script>", "chrome://settings", "file:///etc/passwd"])(
    "turn a %s link into plain text",
    async (href) => {
      await render(`[click](${href})`);
      expect(host.querySelector("a")).toBeNull();
      expect(host.textContent).toContain("click");
    },
  );

  it("show an image as a link instead of loading it", async () => {
    await render("![a chart](https://tracker.example/x.png?q=secret)");
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("a")?.textContent).toBe("Image: a chart");
  });

  it("drop raw HTML", async () => {
    await render('Hello <img src="https://tracker.example/p.gif"> <b>bold</b> <script>alert(1)</script>');
    expect(host.querySelector("img, script, b")).toBeNull();
    expect(host.textContent).toContain("Hello");
  });

  it("render tables and code", async () => {
    await render("| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode here\n```");
    expect(host.querySelectorAll("td")).toHaveLength(2);
    expect(host.querySelector("pre code")?.textContent).toContain("code here");
  });
});
