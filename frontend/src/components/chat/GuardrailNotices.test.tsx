/**
 * @vitest-environment happy-dom
 *
 * What Guardrails did to a turn: a box above the answer per kind, and a
 * refusal in place of an answer - text only, never markup.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import GuardrailNotices, { GuardrailRefusal } from "./GuardrailNotices";

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

describe("the Guardrails boxes", () => {
  it("say each notice under the title of its kind, as text", async () => {
    await act(async () => {
      root.render(
        <GuardrailNotices
          notices={[
            { action: "redact", message: "Card numbers were masked before sending." },
            { action: "route", message: "<b>Answered</b> by Llama." },
          ]}
        />,
      );
    });
    const boxes = [...host.querySelectorAll('[role="note"][aria-label="Guardrails"]')];
    expect(boxes.map((b) => b.className)).toEqual([
      "alpha-router-msg-guardrail alpha-router-msg-guardrail--redact",
      "alpha-router-msg-guardrail alpha-router-msg-guardrail--route",
    ]);
    expect(boxes[0].textContent).toContain("Masked by your organisation's policy");
    expect(boxes[1].querySelector(".alpha-router-msg-guardrail__line")!.textContent).toBe("<b>Answered</b> by Llama.");
    expect(host.querySelector("b")).toBeNull();
  });

  it("show a refusal as the administrator's message", async () => {
    await act(async () => {
      root.render(<GuardrailRefusal message="National codes may not be sent." heldBack />);
    });
    const alert = host.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain("Not sent: your organisation's policy");
    expect(alert.textContent).toContain("National codes may not be sent.");
    expect(alert.textContent).toContain("Message from your administrator");
    expect(alert.textContent).toContain("back in the box below");
  });
});
