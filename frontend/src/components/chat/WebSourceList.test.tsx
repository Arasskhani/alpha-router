/**
 * @vitest-environment happy-dom
 *
 * The pages the web tools read for an answer, shown under it: each a link
 * that opens in a new tab, without handing the page the chat's window.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import WebSourceList from "./WebSourceList";

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

describe("the sources under an answer", () => {
  it("are links to each page, named with its title and site", async () => {
    await act(async () => {
      root.render(
        <WebSourceList
          sources={[
            { title: "Gold price today", url: "https://www.example.com/gold" },
            { title: "Markets", url: "https://news.example/markets" },
          ]}
        />,
      );
    });
    const nav = host.querySelector('nav[aria-label="Sources"]')!;
    const links = [...nav.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://www.example.com/gold",
      "https://news.example/markets",
    ]);
    expect(links[0].textContent).toBe("Gold price todayexample.com");
    for (const a of links) {
      expect(a.target).toBe("_blank");
      expect(a.rel).toContain("noopener");
      expect(a.rel).toContain("noreferrer");
    }
  });
});
