/**
 * @vitest-environment happy-dom
 *
 * The envelope by the chat box: its label, tooltip and pressed state in both
 * positions, and a press asking to switch.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAIL_OFF_LABEL, MAIL_ON_LABEL } from "../lib/mailChatSwitch";
import MailIndicator from "./MailIndicator";

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

const button = () => host.querySelector("button")!;

describe("MailIndicator", () => {
  it("says the mailbox is connected and mail is on, as a pressed toggle", () => {
    act(() => root.render(<MailIndicator on onToggle={() => undefined} />));
    expect(MAIL_ON_LABEL).toBe("Exchange mailbox connected – mail is on for this chat");
    expect(button().getAttribute("aria-label")).toBe(MAIL_ON_LABEL);
    expect(button().getAttribute("title")).toBe(MAIL_ON_LABEL);
    expect(button().getAttribute("aria-pressed")).toBe("true");
    expect(button().type).toBe("button");
    expect(button().className).toContain("alpha-router-composer-ctrl");
    expect(button().className).not.toContain("is-off");
    // The connected envelope (with its tick), and no strike.
    expect(host.querySelectorAll("svg")).toHaveLength(1);
    expect(host.querySelector(".alpha-router-mail-ctrl__strike")).toBeNull();
  });

  it("says mail is off for this chat, muted and struck through", () => {
    act(() => root.render(<MailIndicator on={false} onToggle={() => undefined} />));
    expect(MAIL_OFF_LABEL).toBe("Mail is off for this chat");
    expect(button().getAttribute("aria-label")).toBe(MAIL_OFF_LABEL);
    expect(button().getAttribute("title")).toBe(MAIL_OFF_LABEL);
    expect(button().getAttribute("aria-pressed")).toBe("false");
    expect(button().className).toContain("is-off");
    expect(host.querySelector(".alpha-router-mail-ctrl__strike")).not.toBeNull();
  });

  it("asks to switch when pressed", () => {
    const onToggle = vi.fn();
    act(() => root.render(<MailIndicator on onToggle={onToggle} />));
    act(() => button().click());
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
