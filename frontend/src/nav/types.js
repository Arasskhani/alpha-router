export function isNavGrouped(nav) {
    return nav.length > 0 && "items" in nav[0];
}
export function flattenNav(nav) {
    if (isNavGrouped(nav)) {
        return nav.flatMap((s) => s.items);
    }
    return nav;
}
