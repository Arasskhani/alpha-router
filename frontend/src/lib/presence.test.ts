import { describe, expect, it } from "vitest";
import { PRESENCE_PING_INTERVAL_MS, presenceAvailableFromUserRows } from "./presence";

/** Server default for PRESENCE_TTL_SECONDS, in milliseconds. */
const SERVER_TTL_MS = 90_000;

describe("presence timing", () => {
  it("survives one missed ping", () => {
    expect(PRESENCE_PING_INTERVAL_MS * 2).toBeLessThan(SERVER_TTL_MS);
  });
});

describe("presenceAvailableFromUserRows", () => {
  it("is available when the server resolved presence", () => {
    expect(
      presenceAvailableFromUserRows([{ online: true }, { online: false }]),
    ).toBe(true);
  });

  it("is unavailable when every row is unknown", () => {
    expect(presenceAvailableFromUserRows([{ online: null }, {}])).toBe(false);
  });

  it("does not report an outage for an empty list", () => {
    expect(presenceAvailableFromUserRows([])).toBe(true);
  });
});
