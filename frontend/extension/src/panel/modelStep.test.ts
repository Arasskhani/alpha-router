import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import { frame, json, sse } from "../test/serverFake";
import { modelStep, ModelTimeout } from "./modelStep";

const DONE = [frame({ choices: [{ delta: { content: "ok" }, finish_reason: "stop" }] }), "data: [DONE]\n\n"];

/** A server that answers each try in turn: a finished stream, one that never ends, or a status. */
function server(answers: Array<"ok" | "hang" | number>) {
  const tries: AbortSignal[] = [];
  const request = vi.fn(async (signal: AbortSignal) => {
    tries.push(signal);
    const next = answers.shift() ?? "ok";
    if (typeof next === "number") return json(next, { detail: { code: "x", message: `status ${next}` } });
    return sse(next === "ok" ? DONE : [], { open: next === "hang", signal }).response;
  });
  return { request, tries };
}

describe("a model step", () => {
  it("reads the reply", async () => {
    const s = server(["ok"]);
    await expect(modelStep({ request: s.request }, new AbortController().signal)).resolves.toMatchObject({ text: "ok" });
  });

  it("drops a call that sends nothing for too long, and tries once more", async () => {
    const s = server(["hang", "ok"]);
    const onRetry = vi.fn();
    await expect(modelStep({ request: s.request, idleMs: 30, onRetry }, new AbortController().signal)).resolves.toMatchObject({ text: "ok" });
    expect(s.request).toHaveBeenCalledTimes(2);
    expect(s.tries[0].aborted).toBe(true);
    expect(onRetry).toHaveBeenCalledWith(expect.stringMatching(/sent nothing for/));
  });

  it("gives up after the second try, saying why", async () => {
    const s = server(["hang", "hang"]);
    await expect(modelStep({ request: s.request, idleMs: 30 }, new AbortController().signal)).rejects.toBeInstanceOf(ModelTimeout);
    expect(s.request).toHaveBeenCalledTimes(2);
  });

  it("drops a call that runs past its total time, however it keeps sending", async () => {
    const request = vi.fn(async (signal: AbortSignal) => {
      const stream = sse([], { open: true, signal });
      const beat = setInterval(() => {
        try {
          stream.push(": keep-alive\n\n");
        } catch {
          clearInterval(beat);
        }
      }, 5);
      signal.addEventListener("abort", () => clearInterval(beat));
      return stream.response;
    });
    await expect(modelStep({ request, idleMs: 30, totalMs: 80, retries: 0 }, new AbortController().signal)).rejects.toThrow(/did not finish within/);
  });

  it("keeps waiting while the server keeps the stream alive", async () => {
    const request = vi.fn(async (signal: AbortSignal) => {
      const stream = sse([], { open: true, signal });
      let beats = 0;
      const beat = setInterval(() => {
        beats += 1;
        if (beats < 6) {
          stream.push(": keep-alive\n\n");
          return;
        }
        clearInterval(beat);
        for (const f of DONE) stream.push(f);
        stream.finish();
      }, 15);
      return stream.response;
    });
    await expect(modelStep({ request, idleMs: 40, retries: 0 }, new AbortController().signal)).resolves.toMatchObject({ text: "ok" });
  });

  it("tries again after a stream that was cut short", async () => {
    let tries = 0;
    const request = vi.fn(async (signal: AbortSignal) => {
      tries += 1;
      return sse(tries === 1 ? [frame({ choices: [{ delta: { content: "half" } }] })] : DONE, { signal }).response;
    });
    await expect(modelStep({ request }, new AbortController().signal)).resolves.toMatchObject({ text: "ok" });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("tries again after a server error, but not after a refusal", async () => {
    const failing = server([502, "ok"]);
    await expect(modelStep({ request: failing.request }, new AbortController().signal)).resolves.toMatchObject({ text: "ok" });
    const refused = server([403]);
    await expect(modelStep({ request: refused.request }, new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
    expect(refused.request).toHaveBeenCalledTimes(1);
  });

  it("ends at once on Stop, with no second try", async () => {
    const s = server(["hang", "ok"]);
    const stop = new AbortController();
    const step = modelStep({ request: s.request }, stop.signal);
    await new Promise((resolve) => setTimeout(resolve, 10));
    stop.abort();
    await expect(step).rejects.toMatchObject({ name: "AbortError" });
    expect(s.request).toHaveBeenCalledTimes(1);
  });
});
