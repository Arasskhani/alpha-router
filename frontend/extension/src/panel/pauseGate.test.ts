import { describe, expect, it, vi } from "vitest";

import { createPauseGate } from "./pauseGate";

describe("the pause gate", () => {
  it("lets a run through until paused, and holds it until resumed", async () => {
    const gate = createPauseGate(new AbortController().signal);
    await expect(gate.wait()).resolves.toBeUndefined();
    expect(gate.pause()).toBe(true);
    expect(gate.pause()).toBe(false); // already paused
    let through = false;
    const waiting = gate.wait().then(() => {
      through = true;
    });
    await Promise.resolve();
    expect(through).toBe(false);
    expect(gate.resume()).toBe(true);
    await waiting;
    expect(through).toBe(true);
    expect(gate.resume()).toBe(false); // not paused any more
  });

  it("tells the panel of each change", () => {
    const gate = createPauseGate(new AbortController().signal);
    const seen: boolean[] = [];
    gate.onChange((paused) => seen.push(paused));
    gate.pause();
    gate.resume();
    gate.resume();
    expect(seen).toEqual([true, false]);
  });

  it("ends a wait when the run is stopped, and takes no pause after", async () => {
    const abort = new AbortController();
    const gate = createPauseGate(abort.signal);
    gate.pause();
    const waiting = gate.wait();
    abort.abort();
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
    await expect(gate.wait()).rejects.toMatchObject({ name: "AbortError" });
    expect(gate.pause()).toBe(false);
  });

  it("holds several waiters and lets them all go at once", async () => {
    const gate = createPauseGate(new AbortController().signal);
    gate.pause();
    const done = vi.fn();
    const all = Promise.all([gate.wait().then(done), gate.wait().then(done)]);
    gate.resume();
    await all;
    expect(done).toHaveBeenCalledTimes(2);
  });
});
