import manifest from "../generated/persianFonts.json";
const data = manifest;
/** Catalog discovered at build time from public/fonts. */
export function listPersianFontOptions() {
    return Array.isArray(data.families) ? data.families : [];
}
export function isKnownPersianFontId(id) {
    const trimmed = (id || "").trim();
    if (!trimmed)
        return false;
    return listPersianFontOptions().some((f) => f.id === trimmed);
}
/** Normalize a saved preference; unknown ids fall back to system (""). */
export function normalizePersianFontId(id) {
    const trimmed = (id || "").trim();
    if (!trimmed || trimmed === "system" || trimmed === "default")
        return "";
    return isKnownPersianFontId(trimmed) ? trimmed : "";
}
/**
 * Apply the selected Persian font to chat surfaces via data-persian-font on .alpha-router-app.
 * Empty id clears the attribute (system UI font).
 */
export function applyPersianFontToChat(fontId) {
    const id = normalizePersianFontId(fontId);
    const roots = document.querySelectorAll(".alpha-router-app");
    roots.forEach((el) => {
        if (id)
            el.setAttribute("data-persian-font", id);
        else
            el.removeAttribute("data-persian-font");
    });
}
