import { describe, expect, it } from "vitest";
import { formatLocalDateTime, parseApiDateTime } from "./dateTime";

/**
 * The API stores naive UTC. `new Date("...T10:00:00")` would read that as
 * local time and shift every timestamp by the browser's offset; the parser
 * pins it to UTC. The assertions use getTime() so they hold in any TZ.
 */
describe("parseApiDateTime", () => {
  it("reads a naive API timestamp as UTC, whatever the browser's zone", () => {
    const parsed = parseApiDateTime("2026-09-19T10:00:00");
    expect(parsed?.getTime()).toBe(Date.UTC(2026, 8, 19, 10, 0, 0));
  });

  it("keeps an explicit offset and drops fractional seconds on a naive value", () => {
    expect(parseApiDateTime("2026-09-19T10:00:00+02:00")?.getTime()).toBe(Date.UTC(2026, 8, 19, 8, 0, 0));
    expect(parseApiDateTime("2026-09-19T10:00:00.123456")?.getTime()).toBe(Date.UTC(2026, 8, 19, 10, 0, 0));
  });

  it("returns null rather than an Invalid Date", () => {
    expect(parseApiDateTime("")).toBeNull();
    expect(parseApiDateTime(null)).toBeNull();
    expect(parseApiDateTime("not a date")).toBeNull();
    expect(formatLocalDateTime(undefined)).toBe("—");
  });

  it("differs from the bare constructor by exactly the local offset", () => {
    const naive = "2026-01-15T12:00:00";
    const viaConstructor = new Date(naive).getTime();
    const viaParser = parseApiDateTime(naive)!.getTime();
    const offsetMs = new Date(viaParser).getTimezoneOffset() * 60_000;
    expect(viaConstructor - viaParser).toBe(offsetMs);
  });
});
