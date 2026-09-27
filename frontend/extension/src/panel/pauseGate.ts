/**
 * A pause the person can put on a run - by taking over the page, or from the
 * panel - and lift again. The agent's loop waits at the gate at each of its
 * safe points (before it asks the model, before it judges an action, before it
 * presses); while nobody is waiting, a pause simply holds the next one.
 * Stopping the run ends any wait, whichever came first.
 */

export type PauseGate = {
  paused(): boolean;
  /** Resolves at once when not paused, else once resumed; rejects with the stop's AbortError when the run is stopped. */
  wait(): Promise<void>;
};

export type PauseControl = PauseGate & {
  /** Hold the run at its next safe point; nothing while already paused. Returns whether this call paused it. */
  pause(): boolean;
  /** Let it go on. Returns whether it was paused. */
  resume(): boolean;
  /** Called with each change, for the panel's own view of the state. */
  onChange(listener: (paused: boolean) => void): void;
};

export function createPauseGate(signal: AbortSignal): PauseControl {
  let paused = false;
  let waiters: Array<{ resolve: () => void; reject: (err: unknown) => void }> = [];
  let listener: ((paused: boolean) => void) | null = null;

  const abortError = () => new DOMException("The run was stopped.", "AbortError");
  const release = (fail: boolean) => {
    const waiting = waiters;
    waiters = [];
    for (const waiter of waiting) {
      if (fail) waiter.reject(abortError());
      else waiter.resolve();
    }
  };
  if (signal.aborted) paused = false;
  else signal.addEventListener("abort", () => release(true), { once: true });

  return {
    paused: () => paused,
    pause() {
      if (paused || signal.aborted) return false;
      paused = true;
      listener?.(true);
      return true;
    },
    resume() {
      if (!paused) return false;
      paused = false;
      listener?.(false);
      release(false);
      return true;
    },
    wait() {
      if (signal.aborted) return Promise.reject(abortError());
      if (!paused) return Promise.resolve();
      return new Promise<void>((resolve, reject) => waiters.push({ resolve, reject }));
    },
    onChange(fn) {
      listener = fn;
    },
  };
}
