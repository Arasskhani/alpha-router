import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { formatApiError } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import Modal from "../components/Modal";
import { syncComposerDraft } from "../lib/composerDrafts";
import {
  MAX_ROOM_HANDOFF_BRIEF,
  appendProjectRoomMessage,
  createProjectRoom,
  createProjectRoomHandoff,
  deleteProjectRoom,
  deleteProjectRoomMessage,
  listProjectRoomMessages,
  listProjectRooms,
  syncProjectRooms,
  updateProjectRoomMessage,
  type ProjectRoom,
  type ProjectRoomMessage,
} from "../lib/projectRoomsApi";
import { applyProjectRoomSync, sortProjectRooms } from "../lib/projectRoomSync";
import { inputDirectionForText } from "../lib/textDirection";

type Props = {
  projectId: string;
  canWrite: boolean;
  onHandoff: (targetSessionId: string) => void;
};

function newClientMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `room-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function ProjectRooms({ projectId, canWrite, onHandoff }: Props) {
  const [rooms, setRooms] = useState<ProjectRoom[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ProjectRoomMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [handoffOpen, setHandoffOpen] = useState(false);
  const [handoffTitle, setHandoffTitle] = useState("");
  const [handoffBrief, setHandoffBrief] = useState("");
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [deleteRoomId, setDeleteRoomId] = useState<string | null>(null);
  const [deleteMessageId, setDeleteMessageId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [replyTo, setReplyTo] = useState<ProjectRoomMessage | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const sinceRef = useRef(0);
  const previousIdsRef = useRef<string[]>([]);
  const selectedIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ProjectRoomMessage[]>([]);

  selectedIdRef.current = selectedId;
  messagesRef.current = messages;

  const selected = useMemo(
    () => rooms.find((room) => room.id === selectedId) ?? null,
    [rooms, selectedId],
  );

  const scrollToBottom = useCallback(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const applyGoneSelection = useCallback((nextRooms: ProjectRoom[], currentId: string | null) => {
    if (currentId && nextRooms.some((room) => room.id === currentId)) return currentId;
    return nextRooms[0]?.id ?? null;
  }, []);

  const loadSelectedMessages = useCallback(async (roomId: string) => {
    const data = await listProjectRoomMessages(projectId, roomId, { limit: 200 });
    setMessages(data.messages);
  }, [projectId]);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listProjectRooms(projectId);
      const next = sortProjectRooms(data.rooms);
      setRooms(next);
      previousIdsRef.current = next.map((room) => room.id);
      sinceRef.current = Date.now();
      setSelectedId((current) => applyGoneSelection(next, current));
      setHidden(false);
    } catch (err) {
      if ((err as { status?: number }).status === 404) {
        setHidden(true);
        setRooms([]);
        setSelectedId(null);
        setMessages([]);
      } else {
        setError(formatApiError(err));
      }
    } finally {
      setLoading(false);
    }
  }, [applyGoneSelection, projectId]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      setReplyTo(null);
      setEditingId(null);
      return;
    }
    void loadSelectedMessages(selectedId).catch((err) => setError(formatApiError(err)));
  }, [loadSelectedMessages, selectedId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (hidden) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const after = messagesRef.current.reduce<number | null>((max, message) => {
          if (typeof message.sequence !== "number") return max;
          return max == null ? message.sequence : Math.max(max, message.sequence);
        }, null);
        const sync = await syncProjectRooms(projectId, {
          since: sinceRef.current,
          sessionId: selectedIdRef.current,
          afterSequence: after,
        });
        if (cancelled) return;
        sinceRef.current = sync.serverTimeMs || Date.now();
        setRooms((local) => {
          const applied = applyProjectRoomSync(local, sync, {
            previousSessionIds: previousIdsRef.current,
            activeRoomId: selectedIdRef.current,
            incrementalMessages: after != null,
            activeLocalMessages: messagesRef.current,
          });
          previousIdsRef.current = applied.rooms.map((room) => room.id);
          if (applied.activeMessages) setMessages(applied.activeMessages);
          setSelectedId((current) => applyGoneSelection(applied.rooms, current));
          return applied.rooms;
        });
      } catch (err) {
        if ((err as { status?: number }).status === 404) {
          setHidden(true);
        }
      }
    };
    const id = window.setInterval(() => void tick(), 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [applyGoneSelection, hidden, projectId]);

  async function onCreateRoom(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || creating) return;
    const title = titleDraft.trim() || "New room";
    setCreating(true);
    setError("");
    try {
      const room = await createProjectRoom(projectId, { title });
      setRooms((current) => sortProjectRooms([room, ...current.filter((row) => row.id !== room.id)]));
      setSelectedId(room.id);
      setTitleDraft("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setCreating(false);
    }
  }

  async function onSend(event?: FormEvent) {
    event?.preventDefault();
    if (!canWrite || !selectedId || sending) return;
    const content = draft.trim();
    if (!content) return;
    setSending(true);
    setError("");
    const clientMessageId = newClientMessageId();
    try {
      const message = await appendProjectRoomMessage(projectId, selectedId, {
        content,
        clientMessageId,
        replyToMessageId: replyTo?.id,
      });
      setMessages((current) => {
        if (current.some((row) => row.id === message.id || row.clientMessageId === clientMessageId)) {
          return current.map((row) =>
            row.id === message.id || row.clientMessageId === clientMessageId ? message : row,
          );
        }
        return [...current, message];
      });
      setDraft("");
      setReplyTo(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSending(false);
    }
  }

  async function onSaveEdit() {
    if (!selectedId || !editingId || editBusy) return;
    const content = editingText.trim();
    if (!content) return;
    setEditBusy(true);
    setError("");
    try {
      const updated = await updateProjectRoomMessage(projectId, selectedId, editingId, { content });
      setMessages((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      setEditingId(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setEditBusy(false);
    }
  }

  async function onConfirmDeleteRoom() {
    if (!deleteRoomId) return;
    setError("");
    try {
      await deleteProjectRoom(projectId, deleteRoomId);
      setRooms((current) => current.filter((room) => room.id !== deleteRoomId));
      if (selectedId === deleteRoomId) setSelectedId(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setDeleteRoomId(null);
    }
  }

  async function onConfirmDeleteMessage() {
    if (!selectedId || !deleteMessageId) return;
    setError("");
    try {
      await deleteProjectRoomMessage(projectId, selectedId, deleteMessageId);
      setMessages((current) => current.filter((row) => row.id !== deleteMessageId));
      if (replyTo?.id === deleteMessageId) setReplyTo(null);
      if (editingId === deleteMessageId) setEditingId(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setDeleteMessageId(null);
    }
  }

  async function onHandoffSubmit(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || handoffBusy) return;
    const brief = handoffBrief.trim();
    if (!brief) return;
    setHandoffBusy(true);
    setError("");
    try {
      const result = await createProjectRoomHandoff(projectId, selectedId, {
        title: handoffTitle.trim() || selected?.title,
        brief,
      });
      syncComposerDraft(
        result.targetSessionId,
        result.brief,
        inputDirectionForText(result.brief),
        [],
      );
      setHandoffOpen(false);
      onHandoff(result.targetSessionId);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setHandoffBusy(false);
    }
  }

  if (hidden) {
    return (
      <div className="project-rooms project-rooms--empty">
        <p className="form-hint">Rooms are available to project members only.</p>
      </div>
    );
  }

  return (
    <div className="project-rooms">
      <aside className="project-rooms__sidebar">
        <div className="project-rooms__sidebar-head">
          <h2>Rooms</h2>
          <p className="form-hint">Human discussion only. No model, no AI spend.</p>
        </div>
        {canWrite ? (
          <form className="project-rooms__new" onSubmit={(event) => void onCreateRoom(event)}>
            <input
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.target.value)}
              placeholder="Room title"
              maxLength={512}
              aria-label="New room title"
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={creating}>
              {creating ? "Creating…" : "New room"}
            </button>
          </form>
        ) : null}
        <ul className="project-rooms__list">
          {rooms.map((room) => (
            <li key={room.id}>
              <button
                type="button"
                className={`project-rooms__item${room.id === selectedId ? " project-rooms__item--active" : ""}`}
                onClick={() => setSelectedId(room.id)}
              >
                <span className="project-rooms__item-title">{room.title}</span>
                <span className="project-rooms__item-meta">
                  {room.messageCount} {room.messageCount === 1 ? "message" : "messages"}
                </span>
              </button>
              {canWrite ? (
                <div className="project-rooms__item-actions">
                  <button
                    type="button"
                    className="project-rooms__item-delete"
                    title="Delete room"
                    aria-label={`Delete ${room.title}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setDeleteRoomId(room.id);
                    }}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                    </svg>
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
        {!loading && rooms.length === 0 ? (
          <p className="form-hint">No rooms yet. Start a human thread for one topic.</p>
        ) : null}
      </aside>
      <section className="project-rooms__main">
        {error ? <div className="flash flash-error">{error}</div> : null}
        {loading && !selected ? <div className="loading-state">Loading…</div> : null}
        {!loading && !selected ? (
          <p className="form-hint">Select a room to read the discussion.</p>
        ) : null}
        {selected ? (
          <>
            <header className="project-rooms__header">
              <div>
                <h3>{selected.title}</h3>
                <p className="form-hint">Members only. Messages stay out of Chats and project memory.</p>
              </div>
              {canWrite ? (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setHandoffTitle(selected.title);
                    setHandoffBrief("");
                    setHandoffOpen(true);
                  }}
                >
                  Send decision to Chat
                </button>
              ) : null}
            </header>
            <div className="project-rooms__transcript" ref={transcriptRef}>
              {messages.length === 0 ? (
                <p className="form-hint">No messages yet.</p>
              ) : (
                messages.map((message) => (
                  <article key={message.id || message.clientMessageId} className="project-rooms__msg">
                    <div className="alpha-router-msg-author-label">
                      {message.authorDisplayName || "Member"}
                      {message.edited ? <span className="project-rooms__edited">Edited</span> : null}
                    </div>
                    <div className="project-rooms__bubble">
                      {message.replyToContent ? (
                        <div className="project-rooms__quote">
                          <strong>{message.replyToAuthor || "Member"}</strong>
                          <span>{message.replyToContent}</span>
                        </div>
                      ) : null}
                      {editingId === message.id ? (
                        <div className="project-rooms__edit">
                          <textarea
                            value={editingText}
                            onChange={(event) => setEditingText(event.target.value)}
                            rows={3}
                          />
                          <div className="project-rooms__edit-actions">
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              disabled={editBusy || !editingText.trim()}
                              onClick={() => void onSaveEdit()}
                            >
                              {editBusy ? "Saving…" : "Save"}
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={editBusy}
                              onClick={() => setEditingId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="project-rooms__bubble-body">{message.content}</div>
                      )}
                    </div>
                    {canWrite && editingId !== message.id ? (
                      <div className="alpha-router-msg-actions">
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn"
                          onClick={() => setReplyTo(message)}
                        >
                          Reply
                        </button>
                        {message.mine ? (
                          <>
                            <button
                              type="button"
                              className="alpha-router-msg-action-btn"
                              onClick={() => {
                                setEditingId(message.id);
                                setEditingText(message.content);
                              }}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="alpha-router-msg-action-btn"
                              onClick={() => setDeleteMessageId(message.id)}
                            >
                              Delete
                            </button>
                          </>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                ))
              )}
            </div>
            {canWrite ? (
              <form className="project-rooms__composer" onSubmit={(event) => void onSend(event)}>
                {replyTo ? (
                  <div className="project-rooms__reply-bar">
                    <div>
                      Replying to <strong>{replyTo.authorDisplayName || "Member"}</strong>
                      <span>{replyTo.content}</span>
                    </div>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setReplyTo(null)}>
                      Cancel
                    </button>
                  </div>
                ) : null}
                <div className="project-rooms__composer-row">
                  <textarea
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder={replyTo ? "Write a reply…" : "Write to the room…"}
                    rows={3}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void onSend();
                      }
                    }}
                  />
                  <button type="submit" className="btn btn-primary" disabled={sending || !draft.trim()}>
                    {sending ? "Sending…" : "Send"}
                  </button>
                </div>
              </form>
            ) : (
              <p className="form-hint">You can read rooms. Only Owners and Contributors can write.</p>
            )}
          </>
        ) : null}
      </section>
      <Modal
        open={handoffOpen}
        title="Send decision to Chat"
        onClose={() => !handoffBusy && setHandoffOpen(false)}
      >
        <form className="project-rooms__handoff" onSubmit={(event) => void onHandoffSubmit(event)}>
          <p className="form-hint">
            Only this brief is copied into the new chat box. It is not sent to the model until you press Send.
          </p>
          <label>
            Chat title
            <input
              value={handoffTitle}
              onChange={(event) => setHandoffTitle(event.target.value)}
              maxLength={512}
            />
          </label>
          <label>
            Brief
            <textarea
              value={handoffBrief}
              onChange={(event) => setHandoffBrief(event.target.value.slice(0, MAX_ROOM_HANDOFF_BRIEF))}
              rows={8}
              required
              placeholder="Summarize the decision the model should act on."
            />
          </label>
          <div className="dialog-actions">
            <button type="submit" className="btn btn-primary" disabled={handoffBusy || !handoffBrief.trim()}>
              {handoffBusy ? "Opening…" : "Open in Chat"}
            </button>
            <button
              type="button"
              className="btn btn-ghost dialog-actions-cancel"
              disabled={handoffBusy}
              onClick={() => setHandoffOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      </Modal>
      <ConfirmModal
        open={Boolean(deleteRoomId)}
        title="Delete room"
        message="This deletes the human thread. Existing AI chats are not affected."
        confirmLabel="Delete"
        danger
        onCancel={() => setDeleteRoomId(null)}
        onConfirm={() => void onConfirmDeleteRoom()}
      />
      <ConfirmModal
        open={Boolean(deleteMessageId)}
        title="Delete message"
        message="This removes the message from the room for everyone."
        confirmLabel="Delete"
        danger
        onCancel={() => setDeleteMessageId(null)}
        onConfirm={() => void onConfirmDeleteMessage()}
      />
    </div>
  );
}
