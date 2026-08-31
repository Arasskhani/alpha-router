export type MediaViewerKind = "image" | "video";

export type MediaViewerItem = {
  id: string;
  url: string;
  kind: MediaViewerKind;
  alt?: string;
  title?: string;
};

export function isSlideshowMediaKind(kind: string): kind is MediaViewerKind {
  return kind === "image" || kind === "video";
}

export function findMediaViewerIndex(items: MediaViewerItem[], url: string): number {
  const target = url.trim();
  if (!target) return -1;
  return items.findIndex((item) => item.url === target);
}

export function slideshowItemsFromMedia(
  items: Array<{
    id: number;
    kind: string;
    url: string;
    file_name: string;
    source_prompt?: string;
  }>,
): MediaViewerItem[] {
  const out: MediaViewerItem[] = [];
  for (const item of items) {
    if (!isSlideshowMediaKind(item.kind) || !item.url.trim()) continue;
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
