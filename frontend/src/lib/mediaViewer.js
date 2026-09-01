export function isSlideshowMediaKind(kind) {
    return kind === "image" || kind === "video";
}
export function findMediaViewerIndex(items, url) {
    const target = url.trim();
    if (!target)
        return -1;
    return items.findIndex((item) => item.url === target);
}
export function slideshowItemsFromMedia(items) {
    const out = [];
    for (const item of items) {
        if (!isSlideshowMediaKind(item.kind) || !item.url.trim())
            continue;
        const name = item.file_name.trim();
        const prompt = item.source_prompt?.trim();
        out.push({
            id: `media-${item.id}`,
            url: item.url,
            kind: item.kind,
            alt: name || (item.kind === "video" ? "Video" : "Image"),
            title: prompt || name || undefined,
        });
    }
    return out;
}
