export const ADMIN_IP_MODES = ["off", "monitor", "enforce"];
export const RESERVED_HTTPS_PORTS = [
    8080, 8081, 5432, 6432, 6379, 6333, 6334, 8333, 3310, 9333, 23646,
];
const WILDCARD_NETWORKS = new Set(["0.0.0.0/0", "::/0"]);
export function isReservedHttpsPort(port) {
    if (!Number.isInteger(port) || port < 1 || port > 65535)
        return false;
    return RESERVED_HTTPS_PORTS.includes(port);
}
export function httpsHealthUrl(host, port) {
    const hostname = host.trim() || "127.0.0.1";
    if (port === 443)
        return `https://${hostname}/health`;
    return `https://${hostname}:${port}/health`;
}
export function parseCidrInput(raw) {
    const value = raw.trim();
    if (!value)
        return { ok: false, error: "Enter an IP address or CIDR range." };
    const candidate = value.includes("/") ? value : ipv6Literal(value) ? `${value}/128` : `${value}/32`;
    if (!isPlausibleCidr(candidate)) {
        return { ok: false, error: "Use a valid IPv4/IPv6 address or CIDR (for example 192.168.1.10 or 10.0.0.0/8)." };
    }
    if (WILDCARD_NETWORKS.has(normalizeWildcard(candidate))) {
        return { ok: false, error: "The entire Internet (0.0.0.0/0 or ::/0) cannot be allowlisted." };
    }
    return { ok: true, cidr: candidate };
}
export function canEnableEnforce(args) {
    const ip = (args.clientIp || "").trim();
    if (!ip) {
        return { ok: false, reason: "Your current IP could not be detected. Add it manually before enforcing." };
    }
    const enabled = args.entries.filter((entry) => entry.enabled);
    if (!enabled.length) {
        return { ok: false, reason: "Add at least one enabled IP or CIDR before enforcing the allowlist." };
    }
    const matches = enabled.some((entry) => cidrContainsIp(entry.cidr, ip));
    if (!matches) {
        return { ok: false, reason: `Your current IP (${ip}) is not on the allowlist. Add it before enforcing.` };
    }
    return { ok: true };
}
export function daysUntil(iso, now = new Date()) {
    if (!iso)
        return null;
    const end = new Date(iso);
    if (Number.isNaN(end.getTime()))
        return null;
    const ms = end.getTime() - now.getTime();
    return Math.ceil(ms / 86_400_000);
}
export function expiryBannerLevel(days) {
    if (days == null)
        return "none";
    if (days <= 0)
        return "expired";
    if (days <= 7)
        return "critical";
    if (days <= 30)
        return "warning";
    return "none";
}
export function cidrContainsIp(cidr, ip) {
    const parsed = splitCidr(cidr);
    const addr = parseIp(ip);
    if (!parsed || !addr)
        return false;
    if (parsed.version !== addr.version)
        return false;
    const mask = parsed.prefix;
    if (mask < 0 || mask > (parsed.version === 4 ? 32 : 128))
        return false;
    const shift = (parsed.version === 4 ? 32 : 128) - mask;
    if (shift >= (parsed.version === 4 ? 32 : 128)) {
        return parsed.network === 0n && true;
    }
    const network = parsed.network >> BigInt(shift);
    const host = addr.value >> BigInt(shift);
    return network === host;
}
function ipv6Literal(value) {
    return value.includes(":");
}
function normalizeWildcard(cidr) {
    return cidr.trim().toLowerCase();
}
function isPlausibleCidr(value) {
    const parsed = splitCidr(value);
    if (!parsed)
        return false;
    const max = parsed.version === 4 ? 32 : 128;
    return parsed.prefix >= 0 && parsed.prefix <= max;
}
function splitCidr(value) {
    const trimmed = value.trim();
    const slash = trimmed.lastIndexOf("/");
    const ipPart = slash === -1 ? trimmed : trimmed.slice(0, slash);
    const prefixPart = slash === -1 ? "" : trimmed.slice(slash + 1);
    const addr = parseIp(ipPart);
    if (!addr)
        return null;
    const defaultPrefix = addr.version === 4 ? 32 : 128;
    const prefix = prefixPart === "" ? defaultPrefix : Number(prefixPart);
    if (!Number.isInteger(prefix))
        return null;
    const shift = defaultPrefix - prefix;
    const network = shift >= defaultPrefix ? 0n : (addr.value >> BigInt(shift)) << BigInt(shift);
    return { network, prefix, version: addr.version };
}
function parseIp(value) {
    const raw = value.trim();
    if (!raw)
        return null;
    if (raw.includes(".")) {
        const mapped = raw.toLowerCase().startsWith("::ffff:") ? raw.slice(7) : raw;
        const parts = mapped.split(".");
        if (parts.length !== 4)
            return null;
        const nums = parts.map((part) => Number(part));
        if (nums.some((n) => !Number.isInteger(n) || n < 0 || n > 255))
            return null;
        const valueInt = (((nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3]) >>> 0);
        return { value: BigInt(valueInt), version: 4 };
    }
    if (!raw.includes(":"))
        return null;
    const sections = expandIpv6(raw);
    if (!sections)
        return null;
    let valueInt = 0n;
    for (const section of sections) {
        valueInt = (valueInt << 16n) + BigInt(section);
    }
    return { value: valueInt, version: 6 };
}
function expandIpv6(value) {
    const lower = value.toLowerCase();
    if (lower.includes("."))
        return null;
    const [head, tail] = lower.split("::");
    const headParts = head ? head.split(":") : [];
    const tailParts = tail ? tail.split(":") : [];
    if (lower.includes("::") && lower.indexOf("::") !== lower.lastIndexOf("::"))
        return null;
    const missing = 8 - (headParts.filter(Boolean).length + tailParts.filter(Boolean).length);
    if (!lower.includes("::") && headParts.length !== 8)
        return null;
    if (lower.includes("::") && missing < 0)
        return null;
    const parts = [
        ...headParts.filter(Boolean),
        ...Array.from({ length: Math.max(0, missing) }, () => "0"),
        ...tailParts.filter(Boolean),
    ];
    if (parts.length !== 8)
        return null;
    const nums = [];
    for (const part of parts) {
        if (!/^[0-9a-f]{1,4}$/.test(part))
            return null;
        nums.push(parseInt(part, 16));
    }
    return nums;
}
