/** Copy text to the system clipboard with a legacy fallback. */
export async function copyTextToClipboard(text) {
    const value = text.trim();
    if (!value)
        return false;
    try {
        await navigator.clipboard.writeText(value);
        return true;
    }
    catch {
        try {
            const ta = document.createElement("textarea");
            ta.value = value;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            const ok = document.execCommand("copy");
            ta.remove();
            return ok;
        }
        catch {
            return false;
        }
    }
}
