import { readAttachmentMessage } from "./chatAttachments";
import { parseImageMessage } from "./chatImage";
import { parseVideoMessage } from "./chatVideo";
function attachmentMediaUrl(url, dataUrl) {
    return (url || dataUrl || "").trim();
}
function extractStandaloneMarkdownImage(content) {
    const match = content.match(/!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/i);
    return match?.[1]?.trim() || null;
}
/** Images and videos in conversation order (attachments, generated media, standalone markdown). */
export function collectChatSlideshowItems(messages) {
    const items = [];
    messages.forEach((message, messageIndex) => {
        const content = message.content || "";
        const attach = readAttachmentMessage(content);
        if (attach) {
            attach.attachments.forEach((attachment, attachmentIndex) => {
                if (attachment.kind !== "image")
                    return;
                const url = attachmentMediaUrl(attachment.url, attachment.data_url);
                if (!url)
                    return;
                items.push({
                    id: `attach-${messageIndex}-${attachmentIndex}`,
                    url,
                    kind: "image",
                    alt: attachment.name || "Attached image",
                    title: attachment.name || undefined,
                });
            });
            return;
        }
        const image = parseImageMessage(content);
        if (image?.url?.trim()) {
            const prompt = image.prompt?.trim();
            items.push({
                id: `image-${messageIndex}`,
                url: image.url.trim(),
                kind: "image",
                alt: prompt || "Generated image",
                title: prompt || undefined,
            });
            return;
        }
        const video = parseVideoMessage(content);
        if (video?.url?.trim()) {
            const prompt = video.prompt?.trim();
            items.push({
                id: `video-${messageIndex}`,
                url: video.url.trim(),
                kind: "video",
                alt: prompt || "Generated video",
                title: prompt || undefined,
            });
            return;
        }
        const markdownUrl = extractStandaloneMarkdownImage(content);
        if (markdownUrl) {
            items.push({
                id: `markdown-${messageIndex}`,
                url: markdownUrl,
                kind: "image",
                alt: "Generated image",
            });
        }
    });
    return items;
}
