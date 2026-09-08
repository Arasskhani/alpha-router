import { api } from "../api";
import {
  attachmentKindFromName,
  canProcessAttachmentLocally,
  type ProcessedAttachment,
} from "./chatAttachments";
import { fetchAuthenticatedMediaBlob } from "./mediaUrl";
import type { MediaItem } from "./mediaLibrary";
import type { ProjectMediaItem } from "./projectsApi";
import { listProjectMedia } from "./projectsApi";

export type ComposerAttachMediaCandidate = {
  id: number;
  kind: string;
  fileName: string;
  mimeType: string;
  url: string;
  sizeBytes?: number;
  createdAt?: string | null;
};

export type ComposerAttachEligibility = {
  attachable: boolean;
  reason: string | null;
  processedKind?: "image" | "video" | "audio" | "document";
};

export function normalizeUserMediaItem(item: MediaItem): ComposerAttachMediaCandidate {
  return {
    id: item.id,
    kind: item.kind,
    fileName: item.file_name,
    mimeType: item.mime_type,
    url: item.url,
    sizeBytes: item.size_bytes,
    createdAt: item.created_at,
  };
}

export function normalizeProjectMediaItem(item: ProjectMediaItem): ComposerAttachMediaCandidate {
  return {
    id: item.id,
    kind: item.kind,
    fileName: item.fileName,
    mimeType: item.mimeType,
    url: item.url,
    sizeBytes: item.sizeBytes,
    createdAt: item.createdAt,
  };
}

export function composerAttachEligibility(
  item: ComposerAttachMediaCandidate,
  opts: { privateMode: boolean },
): ComposerAttachEligibility {
  const processedKind = attachmentKindFromName(item.fileName);
  if (!processedKind) {
    return { attachable: false, reason: "This file type cannot be attached to chat." };
  }
  if (opts.privateMode && !canProcessAttachmentLocally(item.fileName)) {
    return {
      attachable: false,
      reason: "Private Mode can only attach images, audio/video, or plain-text files from Media.",
    };
  }
  return { attachable: true, reason: null, processedKind };
}

export function capAttachSelection(
  currentIds: number[],
  togglingId: number,
  remainingSlots: number,
): { ids: number[]; blocked: boolean } {
  if (currentIds.includes(togglingId)) {
    return { ids: currentIds.filter((id) => id !== togglingId), blocked: false };
  }
  if (remainingSlots <= 0 || currentIds.length >= remainingSlots) {
    return { ids: currentIds, blocked: true };
  }
  return { ids: [...currentIds, togglingId], blocked: false };
}

export function attachSlotOverflowMessage(remainingSlots: number): string {
  if (remainingSlots <= 0) {
    return "You can attach no more files. Remove one first.";
  }
  return remainingSlots === 1
    ? "You can attach 1 more file."
    : `You can attach up to ${remainingSlots} more files.`;
}

export function mediaBlobToFile(blob: Blob, item: ComposerAttachMediaCandidate): File {
  let name = item.fileName || "attachment";
  if (!name.includes(".")) {
    const ext = (item.mimeType || blob.type || "").split("/")[1]?.split("+")[0];
    if (ext) name = `${name}.${ext}`;
  }
  return new File([blob], name, {
    type: item.mimeType || blob.type || "application/octet-stream",
  });
}

export async function mediaCandidatesToFiles(
  items: ComposerAttachMediaCandidate[],
): Promise<File[]> {
  const files: File[] = [];
  for (const item of items) {
    const blob = await fetchAuthenticatedMediaBlob(item.url);
    files.push(mediaBlobToFile(blob, item));
  }
  return files;
}

export async function attachMediaIds(opts: {
  mediaIds: number[];
  chatSessionId?: string | null;
  projectId?: string | null;
}): Promise<ProcessedAttachment[]> {
  const mediaIds = [...new Set(opts.mediaIds.filter((id) => Number.isInteger(id) && id > 0))];
  if (!mediaIds.length) return [];
  const body: {
    media_ids: number[];
    chat_session_id?: string;
    project_id?: string;
  } = { media_ids: mediaIds };
  if (opts.chatSessionId) body.chat_session_id = opts.chatSessionId;
  if (opts.projectId) body.project_id = opts.projectId;
  const data = await api<{ attachments: ProcessedAttachment[] }>(
    "/api/chat/attachments/from-media",
    { method: "POST", body: JSON.stringify(body) },
  );
  return data.attachments || [];
}

export async function listComposerAttachMedia(opts: {
  projectId?: string | null;
  query?: string;
  limit?: number;
}): Promise<{ items: ComposerAttachMediaCandidate[]; total: number }> {
  const limit = opts.limit ?? 200;
  const q = opts.query?.trim() || undefined;
  if (opts.projectId) {
    const res = await listProjectMedia(opts.projectId, { q, limit });
    return {
      items: res.items.map(normalizeProjectMediaItem),
      total: res.total,
    };
  }
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (q) params.set("q", q);
  const res = await api<{ items: MediaItem[]; total: number }>(`/api/user/media?${params}`);
  return {
    items: res.items.map(normalizeUserMediaItem),
    total: res.total,
  };
}
