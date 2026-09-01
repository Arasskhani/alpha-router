import { describe, expect, it } from "vitest";
import { canEnableEnforce, cidrContainsIp, daysUntil, expiryBannerLevel, httpsHealthUrl, isReservedHttpsPort, parseCidrInput, } from "./securitySettings";
describe("parseCidrInput", () => {
    it("accepts a host address and a CIDR", () => {
        expect(parseCidrInput("192.168.1.10")).toEqual({ ok: true, cidr: "192.168.1.10/32" });
        expect(parseCidrInput("10.0.0.0/8")).toEqual({ ok: true, cidr: "10.0.0.0/8" });
    });
    it("rejects empty and wildcard ranges", () => {
        expect(parseCidrInput("").ok).toBe(false);
        expect(parseCidrInput("0.0.0.0/0").ok).toBe(false);
        expect(parseCidrInput("not-an-ip").ok).toBe(false);
    });
});
describe("canEnableEnforce", () => {
    it("blocks enforce when the current IP is missing from the list", () => {
        const result = canEnableEnforce({
            clientIp: "203.0.113.9",
            entries: [{ cidr: "10.0.0.0/8", enabled: true }],
        });
        expect(result.ok).toBe(false);
    });
    it("allows enforce when the current IP matches an enabled entry", () => {
        expect(canEnableEnforce({
            clientIp: "10.1.2.3",
            entries: [{ cidr: "10.0.0.0/8", enabled: true }],
        })).toEqual({ ok: true });
    });
});
describe("cidrContainsIp", () => {
    it("matches IPv4 ranges and host addresses", () => {
        expect(cidrContainsIp("10.0.0.0/8", "10.9.8.7")).toBe(true);
        expect(cidrContainsIp("10.0.0.0/8", "11.0.0.1")).toBe(false);
        expect(cidrContainsIp("192.168.1.10/32", "192.168.1.10")).toBe(true);
    });
});
describe("https helpers", () => {
    it("omits :443 from the health URL and flags reserved ports", () => {
        expect(httpsHealthUrl("vpn.example.com", 443)).toBe("https://vpn.example.com/health");
        expect(httpsHealthUrl("vpn.example.com", 8443)).toBe("https://vpn.example.com:8443/health");
        expect(isReservedHttpsPort(8080)).toBe(true);
        expect(isReservedHttpsPort(443)).toBe(false);
    });
});
describe("certificate expiry helpers", () => {
    it("classifies remaining days", () => {
        const now = new Date("2026-08-31T00:00:00Z");
        expect(daysUntil("2026-09-30T00:00:00Z", now)).toBe(30);
        expect(expiryBannerLevel(45)).toBe("none");
        expect(expiryBannerLevel(30)).toBe("warning");
        expect(expiryBannerLevel(7)).toBe("critical");
        expect(expiryBannerLevel(0)).toBe("expired");
    });
});
