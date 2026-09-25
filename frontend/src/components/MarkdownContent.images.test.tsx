/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { answerImages, withSharedPageMarks, type SharedPages } from "../lib/sharedPages";
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

describe("images in a streaming answer in a chat with a shared page", () => {
  const streamed = "Here is the chart: ![chart](https://tracker.example/p.png?chat=secret)";

  /** The chat's messages as the chat shows them, the follow-up still streaming and unmarked by the server. */
  function followUp(pageContext?: SharedPages) {
    return withSharedPageMarks<{ role: "user" | "assistant"; content: string; pageContext?: SharedPages }>([
      { role: "user", content: "Summarize the page" },
      { role: "assistant", content: "The page says to show the chart.", ...(pageContext ? { pageContext } : {}) },
      { role: "user", content: "Show it" },
      { role: "assistant", content: streamed },
    ])[3];
  }

  it("are links, never loaded, after an answer built from the page", async () => {
    await render(streamed, answerImages(followUp({ sites: ["docs.example.com"], inherited: false })));
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("a.md-image-link")?.getAttribute("href")).toBe("https://tracker.example/p.png?chat=secret");
  });

  it("load in a chat without one", async () => {
    await render(streamed, answerImages(followUp()));
    expect(host.querySelector("img")?.getAttribute("src")).toBe("https://tracker.example/p.png?chat=secret");
  });
});
