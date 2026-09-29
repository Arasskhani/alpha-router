import { describe, expect, it } from "vitest";

import { readRecalledChats, recalledChatsLabel } from "./recalledChats";

describe("the earlier chats an answer read from", () => {
  it("are read only from a well-formed server value", () => {
    expect(readRecalledChats([{ id: "s-1", title: "Workout" }, { id: "s-2" }, { title: "no id" }, "x"])).toEqual([
      { id: "s-1", title: "Workout" },
      { id: "s-2", title: "" },
    ]);
    expect(readRecalledChats([])).toBeUndefined();
    expect(readRecalledChats({ id: "s-1" })).toBeUndefined();
    expect(readRecalledChats(Array.from({ length: 20 }, (_, n) => ({ id: `s-${n}` })))).toHaveLength(10);
  });

  it("are counted in the label", () => {
    expect(recalledChatsLabel([{ id: "a", title: "" }])).toBe("Read from 1 earlier chat");
    expect(recalledChatsLabel([{ id: "a", title: "" }, { id: "b", title: "" }])).toBe("Read from 2 earlier chats");
  });
});
