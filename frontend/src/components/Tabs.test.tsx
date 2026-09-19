/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import Tabs, { TabPanel } from "./Tabs";

// React 18's act() needs this flag to behave in a non-test-renderer environment.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Id = "one" | "two" | "three";
const ITEMS = [
  { id: "one" as const, label: "One" },
  { id: "two" as const, label: "Two" },
  { id: "three" as const, label: "Three" },
];

let container: HTMLDivElement;
let root: Root;
let current: Id = "one";

function Harness({ value }: { value: Id }) {
  return (
    <>
      <Tabs
        items={ITEMS}
        value={value}
        onChange={(id) => {
          current = id;
          render(id);
        }}
        ariaLabel="Example"
        idBase="ex"
      />
      <TabPanel idBase="ex" id={value}>
        panel {value}
      </TabPanel>
    </>
  );
}

function render(value: Id) {
  act(() => {
    root.render(<Harness value={value} />);
  });
}

function tabs(): HTMLButtonElement[] {
  return [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
}

function press(el: HTMLElement, key: string) {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("Tabs", () => {
  it("is a tablist whose selected tab is the only one in the Tab order", () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    current = "one";
    render("one");

    expect(container.querySelector('[role="tablist"]')?.getAttribute("aria-label")).toBe("Example");
    const [one, two, three] = tabs();
    expect(one.getAttribute("aria-selected")).toBe("true");
    expect(two.getAttribute("aria-selected")).toBe("false");
    expect(one.tabIndex).toBe(0);
    expect(two.tabIndex).toBe(-1);
    expect(three.tabIndex).toBe(-1);
  });

  it("moves selection and focus with the arrow keys, wrapping at the ends", () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    current = "one";
    render("one");

    press(tabs()[0], "ArrowRight");
    expect(current).toBe("two");
    expect(document.activeElement).toBe(tabs()[1]);

    press(tabs()[1], "ArrowRight");
    press(tabs()[2], "ArrowRight");
    expect(current, "wraps from the last tab to the first").toBe("one");

    press(tabs()[0], "ArrowLeft");
    expect(current, "wraps from the first tab to the last").toBe("three");

    press(tabs()[2], "Home");
    expect(current).toBe("one");
    press(tabs()[0], "End");
    expect(current).toBe("three");
  });

  it("states the tab/panel relationship both ways", () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    current = "two";
    render("two");

    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.id).toBe("ex-panel-two");
    expect(panel.getAttribute("aria-labelledby")).toBe("ex-tab-two");
    expect(tabs()[1].getAttribute("aria-controls")).toBe("ex-panel-two");
  });
});
