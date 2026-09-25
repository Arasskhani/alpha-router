/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import MarkdownContent from "./MarkdownContent";

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

async function render(content: string, images?: "load" | "link") {
  await act(async () => root.render(<MarkdownContent content={content} images={images} />));
}

describe("images in an answer", () => {
  it("load as before by default", async () => {
    await render("![a chart](https://cdn.example.com/chart.png)");
    expect(host.querySelector("img")?.getAttribute("src")).toBe("https://cdn.example.com/chart.png");
  });

  it("become links, never loaded, for an answer built from untrusted text", async () => {
    await render("Look: ![a chart](https://tracker.example/p.png?data=secret) and ![](https://x.example/y.png)", "link");
    expect(host.querySelector("img")).toBeNull();
    const links = [...host.querySelectorAll("a.md-image-link")];
    expect(links.map((a) => a.textContent)).toEqual(["Image: a chart", "Image: open"]);
    expect(links[0].getAttribute("href")).toBe("https://tracker.example/p.png?data=secret");
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keep an unsafe address inert", async () => {
    await render("![x](javascript:alert(1))", "link");
    expect(host.querySelector("a.md-image-link")?.getAttribute("href")).toBe("#");
  });
});
