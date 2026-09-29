/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { observe, stopAnnouncements, watchAnnouncements } from "./observe";
import { markOwn } from "./own";
import { runAgentCall } from "./runtime";

/** What happy-dom cannot lay out: hidden is what carries `hidden` or sits in something that does. */
const visible = (el: Element) => !el.hasAttribute("hidden");
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

afterEach(() => {
  stopAnnouncements(document);
  document.body.innerHTML = "";
});

describe("what the page announced", () => {
  it("is not what the page said before the agent came, but what it says after", () => {
    document.body.innerHTML = `<div role="status">3 results</div><div role="alert" id="a"></div>`;
    watchAnnouncements(document, visible);
    expect(observe(document, visible).said).toEqual([]);
    document.getElementById("a")!.textContent = "Enter a valid address";
    expect(observe(document, visible).said).toEqual([{ kind: "alert", text: "Enter a valid address" }]);
    // Said once: the next look has nothing new.
    expect(observe(document, visible).said).toEqual([]);
  });

  it("keeps a message that came and went between two looks", async () => {
    document.body.innerHTML = `<main></main>`;
    watchAnnouncements(document, visible);
    const toast = document.createElement("div");
    toast.setAttribute("aria-live", "assertive");
    toast.textContent = "Message sent";
    document.body.append(toast);
    await sleep(150);
    toast.remove();
    expect(observe(document, visible).said).toEqual([{ kind: "alert", text: "Message sent" }]);
  });

  it("hears a toast added at the end of a page full of live regions", async () => {
    document.body.innerHTML = Array.from({ length: 80 }, (_, i) => `<div role="status" id="s${i}">Row ${i}</div>`).join("");
    watchAnnouncements(document, visible);
    const toast = document.createElement("div");
    toast.setAttribute("role", "alert");
    document.body.append(toast);
    toast.textContent = "Message sent";
    expect(observe(document, visible).said).toEqual([{ kind: "alert", text: "Message sent" }]);
  });

  it("hears a toast after a burst that changed more announcers than one look takes", async () => {
    document.body.innerHTML = Array.from({ length: 90 }, (_, i) => `<div role="status" id="b${i}">${i}</div>`).join("");
    watchAnnouncements(document, visible);
    for (let i = 0; i < 90; i += 1) document.getElementById(`b${i}`)!.textContent = `badge ${i}`;
    const toast = document.createElement("div");
    toast.setAttribute("role", "alert");
    toast.textContent = "Message sent";
    document.body.append(toast);
    await sleep(30);
    const said = observe(document, visible).said;
    expect(said).toContainEqual({ kind: "alert", text: "Message sent" });
  });

  it("takes what a page loaded after the run began says first as news", () => {
    document.body.innerHTML = `<div role="alert">Your order was placed</div>`;
    const loaded = window.performance.timeOrigin;
    watchAnnouncements(document, visible, loaded - 1000);
    expect(observe(document, visible).said).toEqual([{ kind: "alert", text: "Your order was placed" }]);
    stopAnnouncements(document);
    // A page that was there before the run: what it said is old.
    watchAnnouncements(document, visible, loaded + 1000);
    expect(observe(document, visible).said).toEqual([]);
  });

  it("names a dialog that opened by its label", () => {
    document.body.innerHTML = `<h2 id="t">New message</h2>`;
    watchAnnouncements(document, visible);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-labelledby", "t");
    dialog.textContent = "To Subject Send";
    document.body.append(dialog);
    expect(observe(document, visible).said).toEqual([{ kind: "dialog", text: "New message" }]);
  });

  it("leaves out what a person cannot see, and the agent's own banner", () => {
    document.body.innerHTML = `<div hidden><div role="alert" id="h"></div></div><div id="alpharouter-agent-overlay"><div role="status" id="o"></div></div>`;
    markOwn(document.getElementById("alpharouter-agent-overlay")!);
    watchAnnouncements(document, visible);
    document.getElementById("h")!.textContent = "Hidden words for a model";
    document.getElementById("o")!.textContent = "Stop";
    expect(observe(document, visible).said).toEqual([]);
  });
});

describe("the window's view of the page", () => {
  it("says how much of the page the window shows, in CSS pixels", () => {
    const view = observe(document, visible).view;
    expect(view).toEqual({ width: expect.any(Number), height: expect.any(Number), scrollX: 0, scrollY: 0, pageWidth: expect.any(Number), pageHeight: expect.any(Number) });
    expect(view!.width).toBeGreaterThan(0);
    expect(view!.pageHeight).toBeGreaterThanOrEqual(view!.height);
  });
});

describe("what scrolled under a point", () => {
  it("names the list the wheel turned in, and where it is now", () => {
    document.body.innerHTML = `<div id="list" role="listbox" aria-label="Inbox" style="overflow-y: auto"><div id="row">Row</div></div>`;
    const list = document.getElementById("list")!;
    Object.defineProperty(list, "scrollHeight", { value: 5000, configurable: true });
    Object.defineProperty(list, "clientHeight", { value: 500, configurable: true });
    Object.defineProperty(list, "scrollTop", { value: 400, configurable: true });
    const at = vi.spyOn(document, "elementFromPoint").mockReturnValue(document.getElementById("row"));
    expect(observe(document, visible, { x: 10, y: 10 }).scrolled).toMatch(/^the listbox "Inbox" \[e\d+\] is 400 of 5000 pixels from the top, 4100 more below$/);
    expect(observe(document, visible).scrolled).toBeUndefined();
    at.mockRestore();
  });
});

describe("where the keyboard is", () => {
  it("is the focused field with what it holds, and never what a password field holds", () => {
    document.body.innerHTML = `<input aria-label="To" value="bob@example.com"><input type="password" aria-label="Password" value="hunter2">`;
    const [to, password] = Array.from(document.querySelectorAll("input"));
    to.focus();
    expect(observe(document, visible).focus).toMatchObject({ role: "textbox", name: "To", value: "bob@example.com" });
    password.focus();
    const focus = observe(document, visible).focus;
    expect(focus).toMatchObject({ name: "Password", sensitive: true });
    expect(focus?.value).toBeUndefined();
    password.blur();
    expect(observe(document, visible).focus).toBeUndefined();
  });

  it("goes through the runtime, which starts the watch with the banner and ends it with it", async () => {
    document.body.innerHTML = `<div role="alert" id="a"></div>`;
    const send = () => undefined;
    await runAgentCall(document, "show_overlay", { run: "run-1", label: "Working" }, visible, send);
    document.getElementById("a")!.textContent = "Saved";
    expect(await runAgentCall(document, "observe", {}, visible, send)).toMatchObject({ ok: true, said: [{ kind: "alert", text: "Saved" }] });
    await runAgentCall(document, "hide_overlay", { run: "run-1" }, visible, send);
    // A new watch starts from what is there: nothing new yet.
    expect(await runAgentCall(document, "observe", {}, visible, send)).toMatchObject({ ok: true, said: [] });
  });
});
