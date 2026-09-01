import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { formatApiError } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import Modal from "../components/Modal";
import { syncComposerDraft } from "../lib/composerDrafts";
import { MAX_ROOM_HANDOFF_BRIEF, appendProjectRoomMessage, createProjectRoom, createProjectRoomHandoff, deleteProjectRoom, deleteProjectRoomMessage, listProjectRoomMessages, listProjectRooms, syncProjectRooms, updateProjectRoomMessage, } from "../lib/projectRoomsApi";
import { applyProjectRoomSync, sortProjectRooms } from "../lib/projectRoomSync";
import { inputDirectionForText, messageDirectionForText } from "../lib/textDirection";
function newClientMessageId() {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto)
        return crypto.randomUUID();
    return `room-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
export default function ProjectRooms({ projectId, canWrite, onHandoff }) {
    const [rooms, setRooms] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [messages, setMessages] = useState([]);
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
    const [deleteRoomId, setDeleteRoomId] = useState(null);
    const [deleteMessageId, setDeleteMessageId] = useState(null);
    const [editingId, setEditingId] = useState(null);
    const [editingText, setEditingText] = useState("");
    const [editBusy, setEditBusy] = useState(false);
    const [replyTo, setReplyTo] = useState(null);
    const transcriptRef = useRef(null);
    const sinceRef = useRef(0);
    const previousIdsRef = useRef([]);
    const selectedIdRef = useRef(null);
    const messagesRef = useRef([]);
    selectedIdRef.current = selectedId;
    messagesRef.current = messages;
    const selected = useMemo(() => rooms.find((room) => room.id === selectedId) ?? null, [rooms, selectedId]);
    const draftDir = inputDirectionForText(draft, draft.length);
    const scrollToBottom = useCallback(() => {
        const el = transcriptRef.current;
        if (el)
            el.scrollTop = el.scrollHeight;
    }, []);
    const applyGoneSelection = useCallback((nextRooms, currentId) => {
        if (currentId && nextRooms.some((room) => room.id === currentId))
            return currentId;
        return nextRooms[0]?.id ?? null;
    }, []);
    const loadSelectedMessages = useCallback(async (roomId) => {
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
        }
        catch (err) {
            if (err.status === 404) {
                setHidden(true);
                setRooms([]);
                setSelectedId(null);
                setMessages([]);
            }
            else {
                setError(formatApiError(err));
            }
        }
        finally {
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
        if (hidden)
            return;
        let cancelled = false;
        const tick = async () => {
            try {
                const after = messagesRef.current.reduce((max, message) => {
                    if (typeof message.sequence !== "number")
                        return max;
                    return max == null ? message.sequence : Math.max(max, message.sequence);
                }, null);
                const sync = await syncProjectRooms(projectId, {
                    since: sinceRef.current,
                    sessionId: selectedIdRef.current,
                    afterSequence: after,
                });
                if (cancelled)
                    return;
                sinceRef.current = sync.serverTimeMs || Date.now();
                setRooms((local) => {
                    const applied = applyProjectRoomSync(local, sync, {
                        previousSessionIds: previousIdsRef.current,
                        activeRoomId: selectedIdRef.current,
                        incrementalMessages: after != null,
                        activeLocalMessages: messagesRef.current,
                    });
                    previousIdsRef.current = applied.rooms.map((room) => room.id);
                    if (applied.activeMessages)
                        setMessages(applied.activeMessages);
                    setSelectedId((current) => applyGoneSelection(applied.rooms, current));
                    return applied.rooms;
                });
            }
            catch (err) {
                if (err.status === 404) {
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
    async function onCreateRoom(event) {
        event.preventDefault();
        if (!canWrite || creating)
            return;
        const title = titleDraft.trim() || "New room";
        setCreating(true);
        setError("");
        try {
            const room = await createProjectRoom(projectId, { title });
            setRooms((current) => sortProjectRooms([room, ...current.filter((row) => row.id !== room.id)]));
            setSelectedId(room.id);
            setTitleDraft("");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setCreating(false);
        }
    }
    async function onSend(event) {
        event?.preventDefault();
        if (!canWrite || !selectedId || sending)
            return;
        const content = draft.trim();
        if (!content)
            return;
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
                    return current.map((row) => row.id === message.id || row.clientMessageId === clientMessageId ? message : row);
                }
                return [...current, message];
            });
            setDraft("");
            setReplyTo(null);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setSending(false);
        }
    }
    async function onSaveEdit() {
        if (!selectedId || !editingId || editBusy)
            return;
        const content = editingText.trim();
        if (!content)
            return;
        setEditBusy(true);
        setError("");
        try {
            const updated = await updateProjectRoomMessage(projectId, selectedId, editingId, { content });
            setMessages((current) => current.map((row) => (row.id === updated.id ? updated : row)));
            setEditingId(null);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setEditBusy(false);
        }
    }
    async function onConfirmDeleteRoom() {
        if (!deleteRoomId)
            return;
        setError("");
        try {
            await deleteProjectRoom(projectId, deleteRoomId);
            setRooms((current) => current.filter((room) => room.id !== deleteRoomId));
            if (selectedId === deleteRoomId)
                setSelectedId(null);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setDeleteRoomId(null);
        }
    }
    async function onConfirmDeleteMessage() {
        if (!selectedId || !deleteMessageId)
            return;
        setError("");
        try {
            await deleteProjectRoomMessage(projectId, selectedId, deleteMessageId);
            setMessages((current) => current.filter((row) => row.id !== deleteMessageId));
            if (replyTo?.id === deleteMessageId)
                setReplyTo(null);
            if (editingId === deleteMessageId)
                setEditingId(null);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setDeleteMessageId(null);
        }
    }
    async function onHandoffSubmit(event) {
        event.preventDefault();
        if (!selectedId || handoffBusy)
            return;
        const brief = handoffBrief.trim();
        if (!brief)
            return;
        setHandoffBusy(true);
        setError("");
        try {
            const result = await createProjectRoomHandoff(projectId, selectedId, {
                title: handoffTitle.trim() || selected?.title,
                brief,
            });
            syncComposerDraft(result.targetSessionId, result.brief, inputDirectionForText(result.brief), []);
            setHandoffOpen(false);
            onHandoff(result.targetSessionId);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setHandoffBusy(false);
        }
    }
    if (hidden) {
        return (_jsx("div", { className: "project-rooms project-rooms--empty", children: _jsx("p", { className: "form-hint", children: "Rooms are available to project members only." }) }));
    }
    return (_jsxs("div", { className: "project-rooms", children: [_jsxs("aside", { className: "project-rooms__sidebar", children: [_jsxs("div", { className: "project-rooms__sidebar-head", children: [_jsx("h2", { children: "Rooms" }), _jsx("p", { className: "form-hint", children: "Human discussion only. No model, no AI spend." })] }), canWrite ? (_jsxs("form", { className: "project-rooms__new", onSubmit: (event) => void onCreateRoom(event), children: [_jsx("input", { value: titleDraft, onChange: (event) => setTitleDraft(event.target.value), placeholder: "Room title", maxLength: 512, "aria-label": "New room title" }), _jsx("button", { type: "submit", className: "btn btn-primary btn-sm", disabled: creating, children: creating ? "Creating…" : "New room" })] })) : null, _jsx("ul", { className: "project-rooms__list", children: rooms.map((room) => (_jsxs("li", { children: [_jsxs("button", { type: "button", className: `project-rooms__item${room.id === selectedId ? " project-rooms__item--active" : ""}`, onClick: () => setSelectedId(room.id), children: [_jsx("span", { className: "project-rooms__item-title", children: room.title }), _jsxs("span", { className: "project-rooms__item-meta", children: [room.messageCount, " ", room.messageCount === 1 ? "message" : "messages"] })] }), canWrite ? (_jsx("div", { className: "project-rooms__item-actions", children: _jsx("button", { type: "button", className: "project-rooms__item-delete", title: "Delete room", "aria-label": `Delete ${room.title}`, onClick: (event) => {
                                            event.stopPropagation();
                                            setDeleteRoomId(room.id);
                                        }, children: _jsx("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true", children: _jsx("path", { d: "M6 6l12 12M18 6L6 18", strokeLinecap: "round" }) }) }) })) : null] }, room.id))) }), !loading && rooms.length === 0 ? (_jsx("p", { className: "form-hint", children: "No rooms yet. Start a human thread for one topic." })) : null] }), _jsxs("section", { className: "project-rooms__main", children: [error ? _jsx("div", { className: "flash flash-error", children: error }) : null, loading && !selected ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, !loading && !selected ? (_jsx("p", { className: "form-hint", children: "Select a room to read the discussion." })) : null, selected ? (_jsxs(_Fragment, { children: [_jsxs("header", { className: "project-rooms__header", children: [_jsxs("div", { children: [_jsx("h3", { children: selected.title }), _jsx("p", { className: "form-hint", children: "Members only. Messages stay out of Chats and project memory." })] }), canWrite ? (_jsx("button", { type: "button", className: "btn btn-primary btn-sm", onClick: () => {
                                            setHandoffTitle(selected.title);
                                            setHandoffBrief("");
                                            setHandoffOpen(true);
                                        }, children: "Send decision to Chat" })) : null] }), _jsx("div", { className: "project-rooms__transcript", ref: transcriptRef, children: messages.length === 0 ? (_jsx("p", { className: "form-hint", children: "No messages yet." })) : (messages.map((message) => (_jsxs("article", { className: `project-rooms__msg${message.mine ? " project-rooms__msg--mine" : ""}`, children: [_jsxs("div", { className: "alpha-router-msg-author-label", children: [message.authorDisplayName || "Member", message.edited ? _jsx("span", { className: "project-rooms__edited", children: "Edited" }) : null] }), _jsxs("div", { className: "project-rooms__bubble", children: [message.replyToContent ? (_jsxs("div", { className: "project-rooms__quote", dir: messageDirectionForText(message.replyToContent), children: [_jsx("strong", { children: message.replyToAuthor || "Member" }), _jsx("span", { children: message.replyToContent })] })) : null, editingId === message.id ? (_jsxs("div", { className: "project-rooms__edit", children: [_jsx("textarea", { value: editingText, dir: inputDirectionForText(editingText, editingText.length), onChange: (event) => setEditingText(event.target.value), rows: 3 }), _jsxs("div", { className: "project-rooms__edit-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary btn-sm", disabled: editBusy || !editingText.trim(), onClick: () => void onSaveEdit(), children: editBusy ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", disabled: editBusy, onClick: () => setEditingId(null), children: "Cancel" })] })] })) : (_jsx("div", { className: "project-rooms__bubble-body", dir: messageDirectionForText(message.content), children: message.content }))] }), canWrite && editingId !== message.id ? (_jsxs("div", { className: "alpha-router-msg-actions", children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => setReplyTo(message), children: "Reply" }), message.mine ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => {
                                                                setEditingId(message.id);
                                                                setEditingText(message.content);
                                                            }, children: "Edit" }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => setDeleteMessageId(message.id), children: "Delete" })] })) : null] })) : null] }, message.id || message.clientMessageId)))) }), canWrite ? (_jsxs("form", { className: "project-rooms__composer", onSubmit: (event) => void onSend(event), children: [replyTo ? (_jsxs("div", { className: "project-rooms__reply-bar", children: [_jsxs("div", { children: ["Replying to ", _jsx("strong", { children: replyTo.authorDisplayName || "Member" }), _jsx("span", { dir: messageDirectionForText(replyTo.content), children: replyTo.content })] }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => setReplyTo(null), children: "Cancel" })] })) : null, _jsxs("div", { className: "project-rooms__composer-row", children: [_jsx("textarea", { value: draft, dir: draftDir, onChange: (event) => setDraft(event.target.value), placeholder: replyTo ? "Write a reply…" : "Write to the room…", rows: 3, onKeyDown: (event) => {
                                                    if (event.key === "Enter" && !event.shiftKey) {
                                                        event.preventDefault();
                                                        void onSend();
                                                    }
                                                } }), _jsx("button", { type: "submit", className: "btn btn-primary", disabled: sending || !draft.trim(), children: sending ? "Sending…" : "Send" })] })] })) : (_jsx("p", { className: "form-hint", children: "You can read rooms. Only Owners and Contributors can write." }))] })) : null] }), _jsx(Modal, { open: handoffOpen, title: "Send decision to Chat", onClose: () => !handoffBusy && setHandoffOpen(false), children: _jsxs("form", { className: "project-rooms__handoff", onSubmit: (event) => void onHandoffSubmit(event), children: [_jsx("p", { className: "form-hint", children: "Only this brief is copied into the new chat box. It is not sent to the model until you press Send." }), _jsxs("label", { children: ["Chat title", _jsx("input", { value: handoffTitle, onChange: (event) => setHandoffTitle(event.target.value), maxLength: 512 })] }), _jsxs("label", { children: ["Brief", _jsx("textarea", { value: handoffBrief, onChange: (event) => setHandoffBrief(event.target.value.slice(0, MAX_ROOM_HANDOFF_BRIEF)), rows: 8, required: true, placeholder: "Summarize the decision the model should act on." })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn btn-primary", disabled: handoffBusy || !handoffBrief.trim(), children: handoffBusy ? "Opening…" : "Open in Chat" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", disabled: handoffBusy, onClick: () => setHandoffOpen(false), children: "Cancel" })] })] }) }), _jsx(ConfirmModal, { open: Boolean(deleteRoomId), title: "Delete room", message: "This deletes the human thread. Existing AI chats are not affected.", confirmLabel: "Delete", danger: true, onCancel: () => setDeleteRoomId(null), onConfirm: () => void onConfirmDeleteRoom() }), _jsx(ConfirmModal, { open: Boolean(deleteMessageId), title: "Delete message", message: "This removes the message from the room for everyone.", confirmLabel: "Delete", danger: true, onCancel: () => setDeleteMessageId(null), onConfirm: () => void onConfirmDeleteMessage() })] }));
}
