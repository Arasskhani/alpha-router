import type { ProjectRoom, ProjectRoomMessage, ProjectRoomSyncPayload } from "./projectRoomsApi";

export function sortProjectRooms(rooms: ProjectRoom[]): ProjectRoom[] {
  return [...rooms].sort((a, b) => {
    const aAt = a.lastMessageAt ?? a.updatedAt ?? 0;
    const bAt = b.lastMessageAt ?? b.updatedAt ?? 0;
    return bAt - aAt;
  });
}

function messageKey(message: ProjectRoomMessage): string | null {
  if (message.clientMessageId) return `c:${message.clientMessageId}`;
  if (message.id) return `i:${message.id}`;
  if (typeof message.sequence === "number") return `s:${message.sequence}`;
  return null;
}

export function mergeIncomingRoomMessages(
  local: ProjectRoomMessage[],
  incoming: ProjectRoomMessage[],
  incremental: boolean,
): ProjectRoomMessage[] {
  if (!incoming.length) return local;
  if (!local.length) return incoming;
  if (!incremental) {
    if (incoming.length >= local.length) return incoming;
    const seen = new Set(incoming.map(messageKey).filter((key): key is string => !!key));
    const extras = local.filter((message) => {
      const key = messageKey(message);
      return !key || !seen.has(key);
    });
    return extras.length ? [...incoming, ...extras] : incoming;
  }
  const indexByKey = new Map<string, number>();
  local.forEach((message, index) => {
    const key = messageKey(message);
    if (key) indexByKey.set(key, index);
  });
  let changed = false;
  const next = [...local];
  for (const message of incoming) {
    const key = messageKey(message);
    if (!key) {
      next.push(message);
      changed = true;
      continue;
    }
    const index = indexByKey.get(key);
    if (index == null) {
      indexByKey.set(key, next.length);
      next.push(message);
      changed = true;
      continue;
    }
    const current = next[index];
    if (
      current.content !== message.content ||
      current.id !== message.id ||
      current.edited !== message.edited ||
      current.replyToMessageId !== message.replyToMessageId
    ) {
      next[index] = { ...current, ...message };
      changed = true;
    }
  }
  return changed ? next : local;
}

export function applyProjectRoomSync(
  local: ProjectRoom[],
  sync: ProjectRoomSyncPayload,
  opts: {
    previousSessionIds: string[];
    activeRoomId?: string | null;
    incrementalMessages?: boolean;
    activeLocalMessages?: ProjectRoomMessage[];
  },
): { rooms: ProjectRoom[]; activeMessages: ProjectRoomMessage[] | null } {
  const nextIds = new Set(sync.sessionIds);
  const gone = new Set<string>();
  if (sync.goneSessionId) gone.add(sync.goneSessionId);
  if (sync.completeWindow) {
    for (const room of local) {
      if (!nextIds.has(room.id)) gone.add(room.id);
    }
  } else {
    for (const id of opts.previousSessionIds) {
      if (!nextIds.has(id)) gone.add(id);
    }
  }

  const byId = new Map(local.map((room) => [room.id, room]));
  for (const incoming of sync.sessions) {
    const current = byId.get(incoming.id);
    byId.set(incoming.id, current ? { ...current, ...incoming } : incoming);
  }
  for (const id of gone) byId.delete(id);

  const rooms = sortProjectRooms([...byId.values()]);
  let activeMessages: ProjectRoomMessage[] | null = null;
  if (opts.activeRoomId && sync.messageSessionId === opts.activeRoomId && sync.messages) {
    activeMessages = mergeIncomingRoomMessages(
      opts.activeLocalMessages ?? [],
      sync.messages,
      Boolean(opts.incrementalMessages),
    );
  }
  return { rooms, activeMessages };
}
