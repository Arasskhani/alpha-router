/**
 * @vitest-environment happy-dom
 *
 * What Guardrails did to a turn, under the answer: text only, never markup.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import GuardrailNotices from "./GuardrailNotices";

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

describe("the Guardrails note under an answer", () => {
  it("says each notice, as text", async () => {
    await act(async () => {
      root.render(<GuardrailNotices notices={["Card numbers were masked before sending.", "<b>Answered</b> by Llama."]} />);
    });
    const note = host.querySelector('[role="note"][aria-label="Guardrails"]')!;
    const lines = [...note.querySelectorAll(".alpha-router-msg-guardrail__line")].map((l) => l.textContent);
    expect(lines).toEqual(["Card numbers were masked before sending.", "<b>Answered</b> by Llama."]);
    expect(note.querySelector("b")).toBeNull();
  });
});
