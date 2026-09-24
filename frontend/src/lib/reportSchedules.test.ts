/**
 * The Reports page turns a plain choice into a cron expression the server
 * reads the standard way (0 and 7 are Sunday), and describes the ones it made.
 */
import { describe, expect, it } from "vitest";

import {
  cronFor,
  describeCron,
  describeFilters,
  lastRunBadge,
  parseRecipients,
  scheduleParameters,
  type ScheduleWhen,
} from "./reportSchedules";

const when = (values: Partial<ScheduleWhen>): ScheduleWhen => ({
  frequency: "weekly",
  time: "08:00",
  weekday: 1,
  monthDay: 1,
  cron: "",
  ...values,
});

describe("cronFor", () => {
  it("makes the expression for each choice", () => {
    expect(cronFor(when({ frequency: "daily", time: "07:05" }))).toBe("5 7 * * *");
    expect(cronFor(when({ frequency: "weekly", weekday: 1, time: "08:30" }))).toBe("30 8 * * 1");
    expect(cronFor(when({ frequency: "weekly", weekday: 0, time: "23:59" }))).toBe("59 23 * * 0");
    expect(cronFor(when({ frequency: "monthly", monthDay: 28, time: "00:00" }))).toBe("0 0 28 * *");
  });

  it("passes a custom expression on, tidied", () => {
    expect(cronFor(when({ frequency: "custom", cron: "  0  8 * *   1-5 " }))).toBe("0 8 * * 1-5");
    expect(cronFor(when({ frequency: "custom", cron: "   " }))).toBeNull();
  });

  it("has nothing to make without a time", () => {
    expect(cronFor(when({ time: "" }))).toBeNull();
    expect(cronFor(when({ time: "24:00" }))).toBeNull();
    expect(cronFor(when({ time: "8" }))).toBeNull();
  });
});

describe("describeCron", () => {
  it("says the expressions the page makes in words", () => {
    expect(describeCron("5 7 * * *")).toBe("Every day at 07:05");
    expect(describeCron("30 8 * * 1")).toBe("Every Monday at 08:30");
    expect(describeCron("0 9 * * 0")).toBe("Every Sunday at 09:00");
    expect(describeCron("0 9 * * 7")).toBe("Every Sunday at 09:00");
    expect(describeCron("0 8 * * 1-5")).toBe("Every weekday, Monday to Friday, at 08:00");
    expect(describeCron("0 6 15 * *")).toBe("On day 15 of every month at 06:00");
  });

  it("shows any other expression as it is", () => {
    for (const cron of ["*/15 * * * *", "0 9 1 * 1", "0 9 * 1 *", "0 9 * * 1,3", "0 25 * * *", "0 9 * *", "0 9 32 * *"]) {
      expect(describeCron(cron)).toBe(`Cron: ${cron}`);
    }
  });

  it("round-trips every choice the page offers", () => {
    for (let weekday = 0; weekday < 7; weekday += 1) {
      expect(describeCron(cronFor(when({ weekday }))!)).toMatch(/^Every \w+day at 08:00$/);
    }
    expect(describeCron(cronFor(when({ frequency: "monthly", monthDay: 3 }))!)).toBe("On day 3 of every month at 08:00");
  });
});

describe("parseRecipients", () => {
  it("takes commas, semicolons, spaces and lines", () => {
    expect(parseRecipients(" a@x.com,b@x.com;c@x.com\nd@x.com  e@x.com ,")).toEqual([
      "a@x.com",
      "b@x.com",
      "c@x.com",
      "d@x.com",
      "e@x.com",
    ]);
    expect(parseRecipients("  \n ")).toEqual([]);
  });
});

describe("scheduleParameters", () => {
  it("leaves out what the schedule decides itself", () => {
    expect(
      scheduleParameters({
        report_type: "top_users_by_spend",
        format: "csv",
        start_date: "2026-09-01",
        end_date: "2026-09-30",
        top_n: 5,
        department: "Sales",
      }),
    ).toEqual({ top_n: 5, department: "Sales" });
  });
});

describe("describeFilters", () => {
  it("names the filters a schedule narrows its report by", () => {
    expect(describeFilters({ department: "Sales", plan_id: 3, model_id: "gpt-4o", top_n: 10 })).toBe(
      "Department: Sales · Model: gpt-4o · Plan #3",
    );
    expect(describeFilters({ top_n: 10, department: "", user_id: null })).toBe("");
  });
});

describe("lastRunBadge", () => {
  it("labels each outcome", () => {
    expect(lastRunBadge("sent")).toEqual({ label: "Sent", className: "status-badge status-badge--active" });
    expect(lastRunBadge("partial").label).toBe("Partly sent");
    expect(lastRunBadge("failed").className).toContain("status-badge--failed");
    expect(lastRunBadge("running").label).toBe("Running");
    expect(lastRunBadge(null).label).toBe("Not run yet");
  });
});
