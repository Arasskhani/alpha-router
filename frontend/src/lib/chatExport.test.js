import { describe, expect, it } from "vitest";
import { markdownToCsv } from "./chatExport";
describe("markdownToCsv", () => {
    it("converts a markdown pipe table to CSV", () => {
        const md = `| نام | سن |
| --- | --- |
| علی | ۳۰ |
| سارا | ۲۵ |`;
        const csv = markdownToCsv(md);
        expect(csv.split("\r\n")).toEqual([
            "نام,سن",
            "علی,۳۰",
            "سارا,۲۵",
        ]);
    });
    it("quotes cells containing commas and quotes (RFC 4180)", () => {
        const md = `| a | b |
| --- | --- |
| hello, world | "quoted" |`;
        const csv = markdownToCsv(md);
        expect(csv.split("\r\n")[1]).toBe('"hello, world","""quoted"""');
    });
    it("extracts a ```csv fenced block when no markdown table is present", () => {
        const md = "Here is data:\n\n```csv\nname,age\nali,30\nsara,25\n```\n";
        const csv = markdownToCsv(md);
        expect(csv.split("\r\n")).toEqual(["name,age", "ali,30", "sara,25"]);
    });
    it("falls back to a single-column Content table for plain prose", () => {
        const md = "First line\nSecond line";
        const csv = markdownToCsv(md);
        expect(csv.split("\r\n")).toEqual(["Content", "First line", "Second line"]);
    });
    it("returns empty string for empty content", () => {
        expect(markdownToCsv("")).toBe("");
        expect(markdownToCsv("   ")).toBe("");
    });
    it("handles multiple markdown tables by concatenating sections", () => {
        const md = `| a | b |
| --- | --- |
| 1 | 2 |

| c | d |
| --- | --- |
| 3 | 4 |`;
        const csv = markdownToCsv(md);
        const sections = csv.split("\r\n\r\n");
        expect(sections).toHaveLength(2);
        expect(sections[0].split("\r\n")).toEqual(["a,b", "1,2"]);
        expect(sections[1].split("\r\n")).toEqual(["c,d", "3,4"]);
    });
});
