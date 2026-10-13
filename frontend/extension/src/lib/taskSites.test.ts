/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { namedSites } from "./taskSites";

describe("the sites a task names", () => {
  it.each([
    ["Search Wikipedia for the Silk Road and open the first result", ["wikipedia.org"]],
    ["Open https://www.digikala.com/search?q=laptop and list three prices", ["digikala.com"]],
    ["go to en.wikipedia.org/wiki/Iran", ["wikipedia.org"]],
    ["در دیجی‌کالا قیمت لپ‌تاپ را پیدا کن", ["digikala.com"]],
    ["در ویکی‌پدیا درباره جاده ابریشم بخوان", ["wikipedia.org"]],
    ["Find the repo on GitHub, then check docs.example.co.uk", ["example.co.uk", "github.com"]],
    ["Check my gmail inbox", ["google.com"]],
  ])("%s", (task, sites) => {
    expect(namedSites(task).sort()).toEqual([...sites].sort());
  });

  it("does not take an email address or a file name for a site to visit", () => {
    expect(namedSites("Write to ali@example.com about lunch")).toEqual([]);
    expect(namedSites("Summarize report.pdf from the page")).toEqual([]);
  });

  it("names nothing in a task that names no site", () => {
    expect(namedSites("Fill in this form with my name")).toEqual([]);
  });
});
