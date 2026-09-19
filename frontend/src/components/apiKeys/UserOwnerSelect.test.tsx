/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api", () => ({ api: apiMock.api }));

import UserOwnerSelect from "./UserOwnerSelect";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Deferred<T> = { promise: Promise<T>; resolve: (v: T) => void };
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  apiMock.api.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function type(input: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("UserOwnerSelect", () => {
  it("ignores a slow response to an earlier search once a newer one has answered", async () => {
    const first = deferred<unknown[]>();
    const second = deferred<unknown[]>();
    apiMock.api.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);

    act(() => {
      root.render(<UserOwnerSelect value={null} onChange={() => {}} />);
    });
    const input = container.querySelector("input")!;
    act(() => input.focus());
    act(() => {
      input.dispatchEvent(new Event("focus", { bubbles: true }));
    });

    type(input, "al");
    act(() => {
      vi.advanceTimersByTime(250);
    });
    type(input, "ali");
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(apiMock.api).toHaveBeenCalledTimes(2);

    // The newer search answers first ...
    await act(async () => {
      second.resolve([{ id: 2, username: "alice", email: "alice@test", display_name: null }]);
      await Promise.resolve();
    });
    expect(container.textContent).toContain("alice");

    // ... then the stale one arrives. It must not replace the list.
    await act(async () => {
      first.resolve([{ id: 1, username: "albert", email: "albert@test", display_name: null }]);
      await Promise.resolve();
    });
    expect(container.textContent).toContain("alice");
    expect(container.textContent).not.toContain("albert");
  });
});
