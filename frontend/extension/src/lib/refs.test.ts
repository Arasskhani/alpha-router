import { describe, expect, it } from "vitest";

import { looseName } from "./refs";

describe("looseName", () => {
  it.each([
    ["Inbox (12)", "Inbox (13)"],
    ["Inbox 1,234 unread", "Inbox 1,235 unread"],
    ["Notifications [99+]", "Notifications [3]"],
    ["صندوق ورودی ۵ پیام", "صندوق ورودی ۶ پیام"],
    ["  Send  ", "send"],
  ])("takes %s and %s for the same element: only a count moved", (a, b) => {
    expect(looseName(a)).toBe(looseName(b));
  });

  it.each([
    ["Delete invoice 1041", "Delete invoice 1042"],
    ["Order #20260928", "Order #20260929"],
    ["Row 3", "Row 4"],
  ])("tells %s from %s: the number is what the element is", (a, b) => {
    expect(looseName(a)).not.toBe(looseName(b));
  });
});
