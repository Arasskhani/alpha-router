import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useOutletContext } from "react-router-dom";
import { api, authFetch, formatApiError, getCachedSession, isApiAuthError } from "../api";
import { chatModelsEmptyMessage, normalizeChatModelsError } from "../lib/chatMessages";
import AuthenticatedImage from "./AuthenticatedImage";
import MarkdownContent from "./MarkdownContent";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { useReadOnly } from "../context/ReadOnlyContext";
import { useShellMenu } from "../context/ShellMenuContext";
import { useConfirm } from "../context/ConfirmContext";
import RowActionsMenu from "./RowActionsMenu";
import ColorPickerModal from "./ColorPickerModal";
import {
  fetchAuthenticatedMediaBlob,
  fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl,
} from "../lib/mediaUrl";
import {
  openSafeUrlInNewTab,
  safeBrowserUrl,
} from "../lib/browserUrlPolicy";
import {
  ChatFolder,
  ChatMessage,
  ChatSession,
  createFolder,
  createSession,
  clearLocalChatStorage,
  DEFAULT_CHAT_TITLE,
  fetchUserChatsFromServer,
  hydrateUserPrefsFromServer,
  fetchSessionWithMessages,
  isDefaultChatTitle,
  isPrivateChat,
  loadChatFoldersLocal,
  loadChatSessionsLocal,
  loadSessionMessagesIfNeeded,
  loadOlderSessionMessages,
  resolveNewChatModel,
  saveDefaultModelToServer,
  migrateLegacyChatsToServer,
  syncChatsToServer,
  deleteChatSessionOnServer,
  markPendingDelete,
  fetchChatSessionTitle,
  normalizeMessageForTitle,
  sessionTitleFromMessages,
  sessionTools,
  historyForModelRequest,
  mergeRemoteChatSessions,
  newClientMessageId,
  registerChatSessionsProvider,
  refreshChatsSince,
  commitServerListSync,
  shouldSkipEmptyIncrementalSync,
  registerImmediateChatSync,
  registerPrivateMessagesSync,
  persistChatMessages,
  finalizeAssistantOnServer,
  syncSessionMessagesToServer,
  cancelStreamingReplyOnServer,
  setMessageFeedbackOnServer,
  patchLastSessionMessageOnServer,
  clearSessionMessageSyncQueue,
  replaceChatSessionMessagesOnServer,
  isChatRevisionConflict,
  pollSessionMessagesFromServer,
  searchChatMessagesOnServer,
  isChatSessionOnServer,
  pushSessionMetadataToServer,
  markSessionMetadataDirty,
  enhancePrompt,
  sessionActivityAt,
  withSessionMessagesActivity,
  sidebarTodayCutoffMs,
  sidebarOlderThan3DaysCutoffMs,
  sidebarHydrateMinActivityMs,
} from "../lib/chatStorage";
import { isChatLeader, onChatLeaderChange } from "../lib/chatLeader";
import { formatLocalDateTimeFromMs } from "../lib/dateTime";
import { STORAGE_KEYS } from "../lib/brand";
import { getSessionUser, isSessionActive, logout } from "../lib/session";
import { copyFreshChatTools, toolsToApiPayload, type ChatToolsState } from "../lib/chatTools";
import ChatAttachmentMessage from "./chat/ChatAttachmentMessage";
import ChatAudioMessage from "./chat/ChatAudioMessage";
import ServerToolsMenu from "./chat/ServerToolsMenu";
import {
  ComposerModelIcon,
  ComposerToolsIcon,
  ComposerTranslateIcon,
} from "./chat/ComposerControlIcons";
import VirtualSidebarList from "./chat/ChatSidebarVirtual";
import UserProfile from "./UserProfile";
import PrivateModeLockIcon from "./chat/PrivateModeLockIcon";
import { BrowserSpeechCapture, pickVoiceRecordingMime } from "../lib/voiceInput";
import {
  ATTACHMENT_ACCEPT,
  attachmentDisplayText,
  attachmentMessage,
  buildApiMessageContent,
  buildApiMessageContentAsync,
  type ApiContentPart,
  cloneProcessedAttachments,
  compactChatMessagesForStorage,
  hasApiContent,
  MAX_ATTACHMENTS,
  readAttachmentMessage,
  promptImpliesImageEdit,
  shouldRouteToImageGeneration,
  validateAttachmentFile,
  processAttachmentFilesLocally,
  type ProcessedAttachment,
} from "../lib/chatAttachments";
import {
  buildImageMessage,
  buildStoppedImageMessages,
  mergeChatMessagesPreferLocal,
  IMAGE_PENDING_MARKER,
  isBackgroundImageRunning,
  getBackgroundImageSessionIds,
  lastAssistantImageUrl,
  resolveImageGenerationReferenceAsync,
  runBackgroundImageGeneration,
  sessionHasInFlightGeneration,
  sessionHasPendingImage,
  sessionHasIncompleteTextReply,
  parseImageMessage,
  stopBackgroundImageGeneration,
  stripOrphanImagePending,
  subscribeBackgroundImageUpdates,
  type ImagePayload,
} from "../lib/chatImage";
import {
  findImageGenerationFallbackModel,
  modelSupportsImageToImage,
  modelSupportsImages,
  modelSupportsTextToImage,
  resolveImageGenerationModel as resolveConcreteImageModel,
  resolveSessionModelForTools,
} from "../lib/chatImageModels";
import {
  findAutoRouterModel,
  findGrok43Model,
  isAutoRouterModel,
  resolveDefaultModelPreference,
  shouldMigrateDefaultToGrok43,
} from "../lib/chatModels";
import { copyTextToClipboard } from "../lib/clipboard";
import { isNearScrollBottom, scrollContainerToBottom } from "../lib/chatScroll";
import {
  clearComposerDraft,
  cloneComposerAttachments,
  getComposerDraft,
  syncComposerDraft,
} from "../lib/composerDrafts";
import { inputDirectionForText, messageDirectionForText, textNeedsEnglishTranslation, type TextDirection } from "../lib/textDirection";
import {
  isPrivateBlobRef,
  resolvePrivateBlobRef,
} from "../lib/privateMediaStore";
import {
  COMPOSER_DEFAULT_PLACEHOLDER,
  COMPOSER_WELCOME_PROMPT,
  getChatWelcomeHeading,
  isReturningChatUser,
  shouldShowWelcomeComposerPrompt,
} from "../lib/chatWelcome";

type ShellOutletContext = {
  theme?: "light" | "dark";
  setTheme?: (theme: "light" | "dark") => void;
};

type Model = {
  id: string;
  name: string;
  external_id?: string;
  is_image_model?: boolean;
  supports_text_to_image?: boolean;
  supports_image_to_image?: boolean;
};
type AudioPayload = { url: string; transcript: string };
type QueuedPrompt = {
  id: string;
  text: string;
  attachments: ProcessedAttachment[];
};
type TurnPhase = "preparing" | "searching" | "writing";

function turnPhaseLabel(phase: TurnPhase): string {
  switch (phase) {
    case "searching":
      return "Searching the web…";
    case "writing":
      return "Writing…";
    case "preparing":
    default:
      return "Thinking…";
  }
}
const IMAGE_MESSAGE_PREFIX = "__ALPHA_ROUTER_IMAGE_JSON__:";
const AUDIO_MESSAGE_PREFIX = "__ALPHA_ROUTER_AUDIO_JSON__:";

function shortModelName(name: string, id: string) {
  const n = name || id;
  return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}

function imageMessage(payload: ImagePayload) {
  return buildImageMessage(payload);
}

function audioMessage(payload: AudioPayload) {
  return `${AUDIO_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}

function readAudioMessage(content: string): AudioPayload | null {
  if (content.startsWith(AUDIO_MESSAGE_PREFIX)) {
    try {
      return JSON.parse(content.slice(AUDIO_MESSAGE_PREFIX.length)) as AudioPayload;
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * Remove a user prompt (and the assistant replies that follow it) from a
 * message list, identifying the prompt by its stable `clientMessageId`.
 *
 * `fallbackIndex` is only used when the target has no client id and the message
 * at that index still matches the target's role+content (defensive against the
 * list shifting under a background sync). Returns null when the target can no
 * longer be located safely, so callers can abort instead of deleting the wrong
 * thread.
 */
function removePromptThreadFromMessages(
  source: ChatMessage[],
  target: ChatMessage,
  fallbackIndex?: number,
): ChatMessage[] | null {
  let i = -1;
  if (target.clientMessageId) {
    i = source.findIndex((m) => m.clientMessageId === target.clientMessageId);
  }
  if (i < 0 && target.sentAt != null) {
    i = source.findIndex((m) => m.role === "user" && m.sentAt === target.sentAt);
  }
  if (
    i < 0 &&
    fallbackIndex != null &&
    source[fallbackIndex]?.role === "user" &&
    source[fallbackIndex]?.content === target.content
  ) {
    i = fallbackIndex;
  }
  if (i < 0 || source[i]?.role !== "user") return null;
  const next = [...source];
  next.splice(i, 1);
  while (next[i]?.role === "assistant") {
    next.splice(i, 1);
  }
  return next;
}

function promptTextFromUserContent(content: string): string {
  const attach = readAttachmentMessage(content);
  if (attach) {
    const text = attach.userText.trim();
    if (text) return text;
    if (attach.attachments.some((a) => a.kind === "image")) return "Edit this image";
    return attachmentDisplayText(attach);
  }
  const audio = readAudioMessage(content);
  if (audio?.transcript?.trim()) return audio.transcript.trim();
  return content;
}

function displayTextForMessage(content: string): string {
  const attach = readAttachmentMessage(content);
  if (attach) return attachmentDisplayText(attach);
  const audio = readAudioMessage(content);
  if (audio?.transcript) return audio.transcript;
  const image = readImageMessage(content);
  if (image?.prompt?.trim()) return image.prompt.trim();
  return content;
}

function messageDirectionForContent(content: string): TextDirection {
  if (content === IMAGE_PENDING_MARKER || content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    return "ltr";
  }
  const attach = readAttachmentMessage(content);
  if (attach) {
    return messageDirectionForText(attach.userText || attachmentDisplayText(attach));
  }
  const audio = readAudioMessage(content);
  if (audio?.transcript) return messageDirectionForText(audio.transcript);
  return messageDirectionForText(displayTextForMessage(content));
}

function readImageMessage(content: string): ImagePayload | null {
  if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    try {
      return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
    } catch {
      return null;
    }
  }
  if (content.startsWith("__ALPHA_ROUTER_IMAGE__:")) {
    const legacyUrl = content.slice("__ALPHA_ROUTER_IMAGE__:".length);
    return { url: legacyUrl, prompt: "", model: "" };
  }
  if (content.startsWith("__ALPHA_ROUTER_IMAGE_JSON__:")) {
    try {
      return JSON.parse(content.slice("__ALPHA_ROUTER_IMAGE_JSON__:".length)) as ImagePayload;
    } catch {
      return null;
    }
  }
  if (content.startsWith("__ALPHA_ROUTER_IMAGE__:")) {
    const legacyUrl = content.slice("__ALPHA_ROUTER_IMAGE__:".length);
    return { url: legacyUrl, prompt: "", model: "" };
  }
  return null;
}

function newQueueId() {
  return `q-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function queueItemPreview(item: QueuedPrompt): string {
  if (item.attachments.length) {
    const names = item.attachments.map((a) => a.name).join(", ");
    const text = item.text.trim();
    return text ? `${text} · ${names}` : names;
  }
  return item.text.trim() || "(empty)";
}

function extractMarkdownImage(content: string): { imageUrl: string | null; text: string } {
  const re = /!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/i;
  const m = content.match(re);
  if (!m) return { imageUrl: null, text: content };
  const cleaned = content.replace(re, "").replace(/\n{3,}/g, "\n\n").trim();
  return { imageUrl: m[1], text: cleaned };
}

function formatChatMessageTime(ts?: number): string | null {
  return formatLocalDateTimeFromMs(ts);
}

function chatMessageInfoTitle(message: ChatMessage, role: "user" | "assistant", messages: ChatMessage[], index: number): string {
  if (role === "user") {
    const sent = formatChatMessageTime(message.sentAt);
    return sent ? `Sent: ${sent}` : "Send time not recorded for this message.";
  }
  let promptSent: string | null = null;
  for (let j = index - 1; j >= 0; j -= 1) {
    if (messages[j].role === "user") {
      promptSent = formatChatMessageTime(messages[j].sentAt);
      break;
    }
  }
  const received = formatChatMessageTime(message.receivedAt);
  const lines: string[] = [];
  if (promptSent) lines.push(`Prompt sent: ${promptSent}`);
  if (received) lines.push(`Response received: ${received}`);
  return lines.length ? lines.join("\n") : "Timing not recorded for this message.";
}

function MessageInfoButton({ title }: { title: string }) {
  return (
    <button
      type="button"
      className="cgpt-msg-action-btn cgpt-msg-action-btn--info"
      title={title}
      aria-label={title}
    >
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="7" r="1.65" fill="currentColor" stroke="none" />
        <line x1="12" y1="10" x2="12" y2="18" strokeLinecap="round" />
      </svg>
    </button>
  );
}

function PrivateModeStrip() {
  return (
    <div className="cgpt-private-strip" role="status">
      <PrivateModeLockIcon className="cgpt-private-strip__icon" size={18} />
      <p className="cgpt-private-strip__text">
        <span className="cgpt-private-strip__title">Private Mode is ON</span>
        <span className="cgpt-private-strip__sep" aria-hidden>
          {" "}
          :{" "}
        </span>
        <span className="cgpt-private-strip__body">
          Private Mode is permanent for this chat. Messages and media are stored only in this browser and
          will be <strong className="cgpt-private-strip__danger">deleted</strong> when you log out or clear
          browser data.
        </span>
      </p>
    </div>
  );
}

export default function ChatPanel() {
  const readOnly = useReadOnly();
  const shellMenu = useShellMenu();
  const { confirm } = useConfirm();
  const { theme = "light", setTheme = () => {} } = useOutletContext<ShellOutletContext>() ?? {};
  const [models, setModels] = useState<Model[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [model, setModel] = useState("");
  const [modelSearch, setModelSearch] = useState("");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const sessionUsername = getSessionUser()?.username ?? "";
  const [chatTools, setChatTools] = useState<ChatToolsState>(() => copyFreshChatTools());
  const chatToolsRef = useRef(chatTools);
  chatToolsRef.current = chatTools;
  const [translateToEngBusy, setTranslateToEngBusy] = useState(false);
  const [defaultModel, setDefaultModel] = useState("");
  const userPrefsLoadedRef = useRef(false);
  const serverDefaultModelRef = useRef<string | null | undefined>(undefined);
  const grokDefaultMigrationDoneRef = useRef(false);
  const [historySearch, setHistorySearch] = useState("");
  const [serverSearchQuery, setServerSearchQuery] = useState("");
  const [messageSearchHits, setMessageSearchHits] = useState<
    Array<{ sessionId: string; sessionTitle: string; content: string }>
  >([]);
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false);
  const [olderTotal, setOlderTotal] = useState(0);
  const [pastDaysExpanded, setPastDaysExpanded] = useState(false);
  const [olderExpanded, setOlderExpanded] = useState(false);
  const [olderLoading, setOlderLoading] = useState(false);
  const [olderLoadingMore, setOlderLoadingMore] = useState(false);
  const [olderLoadedCount, setOlderLoadedCount] = useState(0);
  const [messagesLoadingOlder, setMessagesLoadingOlder] = useState(false);
  const [messagesHasOlder, setMessagesHasOlder] = useState(false);
  const [isLeaderTab, setIsLeaderTab] = useState(true);
  const serverSearchTimerRef = useRef<number | null>(null);
  const [chatsHydrated, setChatsHydrated] = useState(false);
  const [hydrateOutcome, setHydrateOutcome] = useState<"pending" | "ok" | "empty" | "error">("pending");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [folders, setFolders] = useState<ChatFolder[]>([]);
  const [newFolderName, setNewFolderName] = useState("");
  const [collapsedFolders, setCollapsedFolders] = useState<Record<string, boolean>>({});
  const [renamingFolderId, setRenamingFolderId] = useState<string | null>(null);
  const [renamingFolderName, setRenamingFolderName] = useState("");
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renamingTitle, setRenamingTitle] = useState("");
  const [colorPickerFolderId, setColorPickerFolderId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [inputDirection, setInputDirection] = useState<TextDirection>("ltr");
  const composerInputRef = useRef("");
  const composerDirectionRef = useRef<TextDirection>("ltr");
  const prevComposerSessionRef = useRef<string | null>(null);
  const restoringComposerRef = useRef(false);
  const [streamingSessions, setStreamingSessions] = useState<Record<string, boolean>>({});
  const [turnPhases, setTurnPhases] = useState<Record<string, TurnPhase>>({});
  const [chatError, setChatError] = useState("");
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  const [draggingSessionId, setDraggingSessionId] = useState<string | null>(null);
  const [dropFolderId, setDropFolderId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  const pinScrollToBottomRef = useRef(true);
  const [showScrollToBottomBtn, setShowScrollToBottomBtn] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const toolsMenuRef = useRef<HTMLDivElement>(null);
  const toolsTriggerRef = useRef<HTMLButtonElement>(null);
  const activeIdRef = useRef<string | null>(null);
  const lastSyncedActiveIdRef = useRef<string | null>(null);
  const serverSaveTimerRef = useRef<number | null>(null);
  const chatsHydratedRef = useRef(false);
  const hydrateGenRef = useRef(0);
  const foldersRef = useRef<ChatFolder[]>([]);
  const sessionsRef = useRef<ChatSession[]>(sessions);
  const abortControllersRef = useRef<Record<string, AbortController>>({});
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const voiceStreamRef = useRef<MediaStream | null>(null);
  const browserSpeechRef = useRef<BrowserSpeechCapture | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<ProcessedAttachment[]>([]);
  const pendingAttachmentsRef = useRef<ProcessedAttachment[]>([]);
  const [attachUploading, setAttachUploading] = useState(false);
  const [promptQueues, setPromptQueues] = useState<Record<string, QueuedPrompt[]>>({});
  const promptQueuesRef = useRef<Record<string, QueuedPrompt[]>>({});
  const streamingSessionsRef = useRef<Record<string, boolean>>({});
  const turnPhasesRef = useRef<Record<string, TurnPhase>>({});
  const streamingMsgsPendingRef = useRef<{ sessionId: string; msgs: ChatMessage[] } | null>(null);
  const streamingMsgsRafRef = useRef<number | null>(null);
  const drainPromisesRef = useRef<Record<string, Promise<void>>>({});
  const drainSessionQueueRef = useRef<(sessionId: string) => Promise<void>>(async () => {});
  const tryDrainPromptQueueRef = useRef<(sessionId: string) => void>(() => {});
  const messagesRef = useRef<ChatMessage[]>([]);

  activeIdRef.current = activeId;
  composerInputRef.current = input;
  composerDirectionRef.current = inputDirection;
  pendingAttachmentsRef.current = pendingAttachments;
  chatsHydratedRef.current = chatsHydrated;
  sessionsRef.current = sessions;
  foldersRef.current = folders;
  messagesRef.current = messages;
  const isSessionStreaming = activeId ? !!streamingSessions[activeId] : false;
  const isStopVisible =
    !!activeId &&
    (isSessionStreaming ||
      isBackgroundImageRunning(activeId) ||
      sessionHasPendingImage(messages));
  const activeTurnPhase = activeId ? turnPhases[activeId] : undefined;
  const activeQueue = activeId ? promptQueues[activeId] || [] : [];
  const returningChatUser = isReturningChatUser(sessions);
  const welcomeHeading = getChatWelcomeHeading({
    username: sessionUsername,
    isReturning: returningChatUser,
  });
  const showWelcomeComposerPrompt = shouldShowWelcomeComposerPrompt({
    messageCount: messages.length,
    input,
    pendingAttachmentCount: pendingAttachments.length,
    queuedPromptCount: activeQueue.length,
  });
  const composerPlaceholder = showWelcomeComposerPrompt
    ? COMPOSER_WELCOME_PROMPT
    : COMPOSER_DEFAULT_PLACEHOLDER;

  const scrollChatToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = messagesScrollRef.current;
    if (el) {
      scrollContainerToBottom(el, behavior);
      return;
    }
    endRef.current?.scrollIntoView({ behavior });
  }, []);

  const maybeScrollChatToBottom = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      if (!pinScrollToBottomRef.current) return;
      scrollChatToBottom(behavior);
    },
    [scrollChatToBottom],
  );

  const syncScrollPinFromContainer = useCallback(() => {
    const el = messagesScrollRef.current;
    if (!el) {
      setShowScrollToBottomBtn(false);
      return;
    }
    if (el.scrollTop > 80) {
      pinScrollToBottomRef.current = false;
    }
    const near = isNearScrollBottom(el);
    if (near) {
      pinScrollToBottomRef.current = true;
    }
    const scrollable = el.scrollHeight > el.clientHeight + 24;
    setShowScrollToBottomBtn(scrollable && !near);
  }, []);

  const jumpToChatBottom = useCallback(() => {
    pinScrollToBottomRef.current = true;
    setShowScrollToBottomBtn(false);
    scrollChatToBottom("smooth");
  }, [scrollChatToBottom]);

  /** Scroll after user message is painted; streaming skips the messages effect. */
  const scrollAfterNewTurn = useCallback(
    (sessionId: string) => {
      if (sessionId !== activeIdRef.current) return;
      pinScrollToBottomRef.current = true;
      setShowScrollToBottomBtn(false);
      requestAnimationFrame(() => {
        scrollChatToBottom("auto");
        requestAnimationFrame(() => scrollChatToBottom("auto"));
      });
    },
    [scrollChatToBottom],
  );

  const filteredModels = useMemo(() => {
    const q = modelSearch.trim().toLowerCase();
    const matched = models.filter((m) => {
      if (chatTools.imageGeneration) {
        if (!modelSupportsImages(m, models)) return false;
      }
      if (!q) return true;
      const name = (m.name || "").toLowerCase();
      const id = (m.id || "").toLowerCase();
      const ext = (m.external_id || "").toLowerCase();
      return name.includes(q) || id.includes(q) || ext.includes(q);
    });
    const autoRouter = findAutoRouterModel(matched);
    if (!autoRouter) return matched;
    return [autoRouter, ...matched.filter((m) => m.id !== autoRouter.id)];
  }, [models, modelSearch, chatTools.imageGeneration]);

  const activeSession = activeId ? sessions.find((s) => s.id === activeId) : null;
  const activePrivateMode = isPrivateChat(activeSession);

  const activeToolCount = useMemo(() => {
    let n = 0;
    if (chatTools.webSearch) n += 1;
    if (chatTools.webFetch) n += 1;
    if (chatTools.imageGeneration) n += 1;
    if (chatTools.codeInterpreter) n += 1;
    if (activePrivateMode) n += 1;
    return n;
  }, [chatTools, activePrivateMode]);

  const inSearchMode = serverSearchQuery.length >= 2;

  const filteredSessions = useMemo(() => {
    const q = historySearch.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, historySearch]);

  const todayRootSessions = useMemo(() => {
    if (inSearchMode) return [];
    const todayStart = sidebarTodayCutoffMs();
    return filteredSessions
      .filter((s) => !s.folderId && sessionActivityAt(s) >= todayStart)
      .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
  }, [filteredSessions, inSearchMode]);

  const pastDaysRootSessions = useMemo(() => {
    if (inSearchMode) return [];
    const todayStart = sidebarTodayCutoffMs();
    const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
    return filteredSessions
      .filter((s) => {
        if (s.folderId) return false;
        const activity = sessionActivityAt(s);
        return activity >= threeDaysStart && activity < todayStart;
      })
      .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
  }, [filteredSessions, inSearchMode]);

  const olderRootSessions = useMemo(() => {
    if (inSearchMode) return [];
    const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
    return filteredSessions
      .filter((s) => !s.folderId && sessionActivityAt(s) < threeDaysStart)
      .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
  }, [filteredSessions, inSearchMode]);

  const searchRootSessions = useMemo(
    () => (inSearchMode ? filteredSessions.filter((s) => !s.folderId) : []),
    [filteredSessions, inSearchMode],
  );

  const displayOlderCount = useMemo(() => {
    if (inSearchMode) return 0;
    const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
    const privateOlder = sessions.filter(
      (s) => isPrivateChat(s) && !s.folderId && sessionActivityAt(s) < threeDaysStart,
    ).length;
    return Math.max(0, olderTotal) + privateOlder;
  }, [sessions, olderTotal, inSearchMode]);

  useEffect(() => {
    return onChatLeaderChange(setIsLeaderTab);
  }, []);

  useEffect(() => {
    const q = historySearch.trim();
    if (serverSearchTimerRef.current) window.clearTimeout(serverSearchTimerRef.current);
    if (q.length < 2) {
      setServerSearchQuery("");
      setMessageSearchHits([]);
      return;
    }
    serverSearchTimerRef.current = window.setTimeout(() => {
      setServerSearchQuery(q);
      void searchChatMessagesOnServer(q)
        .then((hits) =>
          setMessageSearchHits(
            hits.map((h) => ({
              sessionId: h.sessionId,
              sessionTitle: h.sessionTitle,
              content: h.content,
            })),
          ),
        )
        .catch(() => setMessageSearchHits([]));
    }, 400);
    return () => {
      if (serverSearchTimerRef.current) window.clearTimeout(serverSearchTimerRef.current);
    };
  }, [historySearch]);

  useEffect(() => {
    if (!serverSearchQuery || serverSearchQuery.length < 2) return;
    let cancelled = false;
    void fetchUserChatsFromServer({ q: serverSearchQuery, limit: 30 })
      .then((remote) => {
        if (cancelled) return;
        setSessions((prev) => mergeRemoteChatSessions(prev, remote.sessions));
        setSessionsTotal(remote.total ?? remote.sessions.length);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [serverSearchQuery]);
  const rootSessions = searchRootSessions;
  const sessionsByFolder = useMemo(() => {
    const grouped: Record<string, ChatSession[]> = {};
    for (const s of filteredSessions) {
      if (!s.folderId) continue;
      if (!grouped[s.folderId]) grouped[s.folderId] = [];
      grouped[s.folderId].push(s);
    }
    return grouped;
  }, [filteredSessions]);

  const currentModel = models.find((m) => m.id === model);

  function sessionPrivateMode(sessionId: string): boolean {
    return isPrivateChat(sessionsRef.current.find((s) => s.id === sessionId));
  }

  function resolveModelForSession(session: ChatSession): string {
    return resolveSessionModelForTools(
      models,
      session.model,
      sessionTools(session).imageGeneration,
      (current) => resolveNewChatModel(models, current, defaultModel),
    );
  }

  function persistSessionModelCorrection(sessionId: string, modelId: string) {
    persistSessions(
      (prev) =>
          prev.map((s) =>
            s.id === sessionId ? { ...s, model: modelId } : s,
          ),
      { debounce: false, metadataSessionIds: [sessionId] },
    );
    if (!sessionPrivateMode(sessionId)) {
      void pushSessionMetadataToServer(sessionId).catch(() => {});
    }
  }

  function applyModelFromSession(session: ChatSession) {
    const resolved = resolveModelForSession(session);
    setModel(resolved);
    if (session.model !== resolved) {
      persistSessionModelCorrection(session.id, resolved);
    }
  }

  function isLocalTurnInFlight(sessionId: string): boolean {
    return !!(abortControllersRef.current[sessionId] || streamingSessionsRef.current[sessionId]);
  }

  /**
   * True only while this tab itself is producing output (text stream fetch or
   * background image job). Unlike isLocalTurnInFlight it ignores the streaming
   * display flag, which is also set for server-side pending replies — gating
   * server polls on that flag would deadlock recovery (the poll sets the flag,
   * then blocks itself on it, so a stale pending marker never resolves).
   */
  function isLocalWorkInFlight(sessionId: string): boolean {
    return !!abortControllersRef.current[sessionId] || isBackgroundImageRunning(sessionId);
  }

  function getLocalMessagesForSession(sessionId: string): ChatMessage[] {
    if (sessionId === activeIdRef.current && messagesRef.current.length) {
      return messagesRef.current;
    }
    return sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
  }

  function preferLocalMessagesOverRemote(sessionId: string, remote: ChatMessage[]): ChatMessage[] {
    return mergeChatMessagesPreferLocal(
      getLocalMessagesForSession(sessionId),
      remote,
      isLocalWorkInFlight(sessionId),
    );
  }

  /** Surface API errors from user-initiated actions (send, delete, attach, …). */
  function reportUserFacingApiError(err: unknown) {
    if (isApiAuthError(err)) {
      setChatError("نشست شما منقضی شده است. در حال انتقال به صفحه ورود…");
      window.setTimeout(() => logout(), 1500);
      return;
    }
    setChatError(formatApiError(err));
  }

  /** Background sync failures must not block or alarm the user when the chat turn itself succeeded. */
  function reportSyncError(err: unknown, sessionId?: string) {
    if (isChatRevisionConflict(err)) return;
    if (sessionId && isBackgroundImageRunning(sessionId)) return;
    if (!sessionId && getBackgroundImageSessionIds().length > 0) return;
    if (sessionId && isLocalTurnInFlight(sessionId)) return;
    if (sessionId && streamingSessionsRef.current[sessionId]) return;
    if (!sessionId && Object.values(streamingSessionsRef.current).some(Boolean)) return;
    if (isApiAuthError(err)) {
      logout();
      return;
    }
    console.warn("[alpha-router] background chat sync failed:", formatApiError(err));
  }

  const scheduleServerChatSave = useCallback(
    (opts?: { debounce?: boolean }) => {
      const flush = () => {
        if (serverSaveTimerRef.current) {
          window.clearTimeout(serverSaveTimerRef.current);
          serverSaveTimerRef.current = null;
        }
        if (!chatsHydratedRef.current || readOnly) return;
        if (!getCachedSession()) return;
        const sessionsForServer = sessionsRef.current.map((s) => ({
          ...s,
          messages: s.privateMode ? s.messages : compactChatMessagesForStorage(s.messages),
        }));
        void syncChatsToServer(sessionsForServer, foldersRef.current).catch((err) => {
          reportSyncError(err);
        });
      };
      if (opts?.debounce === false) {
        flush();
        return;
      }
      if (serverSaveTimerRef.current) window.clearTimeout(serverSaveTimerRef.current);
      serverSaveTimerRef.current = window.setTimeout(flush, 400);
    },
    [readOnly],
  );

  const persistSessions = useCallback(
    (
      next: ChatSession[] | ((prev: ChatSession[]) => ChatSession[]),
      opts?: { debounce?: boolean; metadataSessionIds?: string[] },
    ) => {
      setSessions((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        sessionsRef.current = resolved;
        const metaIds = opts?.metadataSessionIds;
        if (metaIds?.length) {
          for (const id of metaIds) {
            const row = resolved.find((s) => s.id === id);
            if (row && !row.privateMode) markSessionMetadataDirty(id);
          }
        }
        scheduleServerChatSave({ debounce: opts?.debounce !== false });
        return resolved;
      });
    },
    [scheduleServerChatSave],
  );

  const patchDefaultTitleFromMessages = useCallback(
    (sid: string, msgs: ChatMessage[]) => {
      const session = sessionsRef.current.find((s) => s.id === sid);
      if (!session || session.titleLocked || !isDefaultChatTitle(session.title)) return;
      const title = sessionTitleFromMessages(msgs);
      if (isDefaultChatTitle(title)) return;
      persistSessions(
        (prev) =>
          prev.map((s) => (s.id === sid ? { ...s, title } : s)),
        { debounce: false, metadataSessionIds: [sid] },
      );
    },
    [persistSessions],
  );

  const updateSessionMessages = useCallback((sessionId: string, msgs: ChatMessage[]) => {
    if (sessionId === activeIdRef.current) {
      messagesRef.current = msgs;
      setMessages(msgs);
    }
    const next = sessionsRef.current.map((s) =>
      s.id === sessionId ? withSessionMessagesActivity(s, msgs) : s,
    );
    sessionsRef.current = next;
    setSessions(next);
  }, []);

  const cancelStreamingMessagesFlush = useCallback(() => {
    if (streamingMsgsRafRef.current != null) {
      cancelAnimationFrame(streamingMsgsRafRef.current);
      streamingMsgsRafRef.current = null;
    }
    streamingMsgsPendingRef.current = null;
  }, []);

  const flushStreamingMessages = useCallback(() => {
    streamingMsgsRafRef.current = null;
    const pending = streamingMsgsPendingRef.current;
    if (!pending) return;
    streamingMsgsPendingRef.current = null;
    const { sessionId, msgs } = pending;
    if (sessionId === activeIdRef.current) {
      messagesRef.current = msgs;
      setMessages(msgs);
    }
    const nextSessions = sessionsRef.current.map((s) =>
      s.id === sessionId ? withSessionMessagesActivity(s, msgs) : s,
    );
    sessionsRef.current = nextSessions;
    setSessions(nextSessions);
    if (pinScrollToBottomRef.current) {
      const el = messagesScrollRef.current;
      if (el) scrollContainerToBottom(el, "auto");
    }
  }, []);
  const scheduleSessionTitle = useCallback(
    async (sid: string, modelId: string, msgs: ChatMessage[]) => {
      const session = sessionsRef.current.find((s) => s.id === sid);
      if (!session || session.titleLocked || session.titleGenerated) return;

      const plainMsgs = msgs.map((m) => ({
        role: m.role,
        content: normalizeMessageForTitle(m.content),
      })) as ChatMessage[];
      const fallback = sessionTitleFromMessages(plainMsgs);

      if (!isDefaultChatTitle(fallback)) {
        persistSessions(
          (prev) =>
            prev.map((s) =>
              s.id === sid && isDefaultChatTitle(s.title) ? { ...s, title: fallback } : s,
            ),
          { debounce: false, metadataSessionIds: [sid] },
        );
        if (!sessionPrivateMode(sid)) {
          await pushSessionMetadataToServer(sid);
        }
      }

      if (!msgs.some((m) => m.role === "assistant" && (m.content || "").trim())) return;

      const generated = await fetchChatSessionTitle(modelId, plainMsgs.slice(0, 6));
      let title =
        generated && !isDefaultChatTitle(generated) ? generated : fallback;
      if (
        generated &&
        !isDefaultChatTitle(fallback) &&
        generated.length < 4 &&
        fallback.length > generated.length
      ) {
        title = fallback;
      }
      if (isDefaultChatTitle(title)) return;

      persistSessions(
        (prev) =>
          prev.map((s) => {
            if (s.id !== sid) return s;
            if (s.titleLocked) return s;
            const current = (s.title || "").trim();
            if (
              !isDefaultChatTitle(current) &&
              current.length > title.length + 2 &&
              title.length < 4
            ) {
              return s;
            }
            return { ...s, title, titleGenerated: true };
          }),
        { debounce: false, metadataSessionIds: [sid] },
      );
      if (!sessionPrivateMode(sid)) {
        await pushSessionMetadataToServer(sid);
      }
    },
    [persistSessions],
  );

  const persistFolders = useCallback(
    (next: ChatFolder[] | ((prev: ChatFolder[]) => ChatFolder[])) => {
      setFolders((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        foldersRef.current = resolved;
        scheduleServerChatSave({ debounce: false });
        return resolved;
      });
    },
    [scheduleServerChatSave],
  );

  const applyMessages = useCallback(
    (sessionId: string, msgs: ChatMessage[], opts?: { debounce?: boolean }) => {
      cancelStreamingMessagesFlush();
      updateSessionMessages(sessionId, msgs);
      if (opts?.debounce === false) {
        scheduleServerChatSave({ debounce: false });
      }
    },
    [cancelStreamingMessagesFlush, updateSessionMessages, scheduleServerChatSave],
  );

  const syncSessionsFromServer = useCallback(async (sessionId?: string | null) => {
    if (!chatsHydratedRef.current) return;
    try {
      const remote = await refreshChatsSince();
      if (remote.incremental && shouldSkipEmptyIncrementalSync(remote)) {
        return;
      }
      const protectedIds = new Set<string>([
        ...Object.keys(streamingSessionsRef.current),
        ...getBackgroundImageSessionIds(),
      ]);
      let merged = mergeRemoteChatSessions(sessionsRef.current, remote.sessions, protectedIds);
      const sid = sessionId ?? activeIdRef.current;
      if (sid) {
        const idx = merged.findIndex((x) => x.id === sid);
        if (idx >= 0 && !isLocalWorkInFlight(sid)) {
          const loaded = await loadSessionMessagesIfNeeded(merged[idx]);
          merged = merged.map((s, i) => (i === idx ? loaded : s));
        }
      }
      setSessions(merged);
      sessionsRef.current = merged;
      if (sid) {
        const s = merged.find((x) => x.id === sid);
        if (s && sid === activeIdRef.current) {
          if (!isLocalWorkInFlight(sid)) {
            setMessages(preferLocalMessagesOverRemote(sid, s.messages));
          }
        }
        if (isBackgroundImageRunning(sid)) {
          setSessionStreaming(sid, true);
        } else if (!abortControllersRef.current[sid]) {
          // Decide streaming from the locally-preferred view: a lagging server copy
          // must not revive "generating" after the local turn already completed.
          const decisionMsgs = preferLocalMessagesOverRemote(sid, s?.messages ?? []);
          if (sessionHasIncompleteTextReply(decisionMsgs)) {
            setSessionStreaming(sid, true);
          } else if (sessionHasPendingImage(decisionMsgs)) {
            setSessionStreaming(sid, true);
          } else {
            setSessionStreaming(sid, false);
          }
        }
      }
    } catch {
      /* ignore refresh errors */
    }
  }, []);

  const deferSessionTitle = useCallback(
    (sid: string, modelId: string, msgs: ChatMessage[]) => {
      window.setTimeout(() => {
        void scheduleSessionTitle(sid, modelId, msgs);
      }, 1200);
    },
    [scheduleSessionTitle],
  );

  const applyMessagesStreaming = useCallback(
    (sessionId: string, msgs: ChatMessage[]) => {
      streamingMsgsPendingRef.current = { sessionId, msgs };
      if (streamingMsgsRafRef.current != null) return;
      streamingMsgsRafRef.current = requestAnimationFrame(() => {
        flushStreamingMessages();
      });
    },
    [flushStreamingMessages],
  );

  useEffect(() => {
    if (readOnly) {
      setModels([]);
      setModelsError("");
      return;
    }
    api<Model[]>("/api/chat/models")
      .then((m) => {
        setModels(m);
        setModelsError(m.length ? "" : chatModelsEmptyMessage());
        if (m.length && !model) {
          setModel(resolveNewChatModel(m, undefined, defaultModel));
        }
      })
      .catch((e) => {
        setModels([]);
        setModelsError(normalizeChatModelsError(e));
      });
  }, [readOnly, defaultModel]);

  useEffect(() => {
    if (!models.length || !activeId || !chatsHydrated) return;
    const session = sessionsRef.current.find((s) => s.id === activeId);
    if (!session) return;
    const resolved = resolveSessionModelForTools(
      models,
      session.model,
      sessionTools(session).imageGeneration,
      (current) => resolveNewChatModel(models, current, defaultModel),
    );
    setModel((prev) => (prev === resolved ? prev : resolved));
    if (session.model !== resolved) {
      persistSessions(
        (prev) =>
          prev.map((s) =>
            s.id === session.id ? { ...s, model: resolved } : s,
          ),
        { debounce: false, metadataSessionIds: [session.id] },
      );
      if (!session.privateMode) {
        void pushSessionMetadataToServer(session.id).catch(() => {});
      }
    }
  }, [models, activeId, chatsHydrated, defaultModel, persistSessions]);

  useEffect(() => {
    if (readOnly || !sessionUsername) return;
    userPrefsLoadedRef.current = false;
    serverDefaultModelRef.current = undefined;
    grokDefaultMigrationDoneRef.current = false;
    let cancelled = false;
    void hydrateUserPrefsFromServer()
      .then((prefs) => {
        if (cancelled) return;
        userPrefsLoadedRef.current = true;
        serverDefaultModelRef.current = prefs.default_model;
        setDefaultModel(prefs.default_model || "");
      })
      .catch(() => {
        if (cancelled) return;
        userPrefsLoadedRef.current = true;
        serverDefaultModelRef.current = null;
        setDefaultModel("");
      });
    return () => {
      cancelled = true;
    };
  }, [readOnly, sessionUsername]);

  useEffect(() => {
    if (!models.length || !defaultModel) return;
    const resolved = resolveDefaultModelPreference(models, defaultModel);
    if (!resolved) {
      if (models.some((m) => m.id === defaultModel)) return;
      setDefaultModel("");
      return;
    }
    if (resolved !== defaultModel) {
      setDefaultModel(resolved);
      void saveDefaultModelToServer(resolved)
        .then((saved) => setDefaultModel(saved || resolved))
        .catch(() => {});
    }
  }, [models, defaultModel]);

  useEffect(() => {
    if (readOnly || !models.length || grokDefaultMigrationDoneRef.current) return;
    if (!userPrefsLoadedRef.current || serverDefaultModelRef.current === undefined) return;
    if (serverDefaultModelRef.current) {
      grokDefaultMigrationDoneRef.current = true;
      return;
    }
    if (!shouldMigrateDefaultToGrok43(models, defaultModel)) {
      grokDefaultMigrationDoneRef.current = true;
      return;
    }
    const grok = findGrok43Model(models);
    grokDefaultMigrationDoneRef.current = true;
    if (!grok) return;
    setDefaultModel(grok.id);
    void saveDefaultModelToServer(grok.id)
      .then((saved) => {
        setDefaultModel(saved || grok.id);
        serverDefaultModelRef.current = saved || grok.id;
      })
      .catch(() => {});
  }, [readOnly, models, defaultModel]);

  useEffect(() => {
    if (!models.length || !model) return;
    if (models.some((m) => m.id === model)) return;
    const byExternal = models.find((m) => m.external_id === model);
    if (byExternal) {
      setModel(byExternal.id);
      return;
    }
    // Stale cached model (e.g. from old dev run / reset DB) -> auto-heal to default/first available model.
    setModel(resolveNewChatModel(models, undefined, defaultModel));
  }, [models, model, defaultModel]);

  useEffect(() => {
    const gen = ++hydrateGenRef.current;
    (async () => {
      try {
        const remote = await fetchUserChatsFromServer({
          limit: 50,
          min_activity_ms: sidebarHydrateMinActivityMs(),
        });
        if (gen !== hydrateGenRef.current) return;
        const localSessions = loadChatSessionsLocal();
        const localFolders = loadChatFoldersLocal();
        let nextSessions = remote.sessions;
        let nextFolders = remote.folders;
        let recentTotal = remote.total ?? remote.sessions.length;
        let olderTotalValue = remote.older_total ?? 0;
        const readOnlyNow = !isSessionActive();
        if (
          !readOnlyNow &&
          !nextSessions.length &&
          (localSessions.length || localFolders.length)
        ) {
          nextSessions = localSessions;
          nextFolders = localFolders.length ? localFolders : remote.folders;
          await migrateLegacyChatsToServer(nextSessions, nextFolders);
          clearLocalChatStorage();
          if (gen !== hydrateGenRef.current) return;
          const afterMigrate = await fetchUserChatsFromServer({
            limit: 50,
            min_activity_ms: sidebarHydrateMinActivityMs(),
          });
          if (gen !== hydrateGenRef.current) return;
          nextSessions = afterMigrate.sessions;
          nextFolders = afterMigrate.folders;
          recentTotal = afterMigrate.total ?? nextSessions.length;
          olderTotalValue = afterMigrate.older_total ?? 0;
        }
        sessionsRef.current = nextSessions;
        commitServerListSync(nextSessions);
        setSessions(nextSessions);
        setFolders(nextFolders);
        setSessionsTotal(recentTotal);
        setOlderTotal(olderTotalValue);
        setOlderLoadedCount(0);
        setPastDaysExpanded(false);
        setOlderExpanded(false);
        setChatsHydrated(true);
        setHydrateOutcome(nextSessions.length > 0 ? "ok" : "empty");
        setChatError("");
        if (nextSessions.length > 0) {
          const first = nextSessions[0];
          activeIdRef.current = first.id;
          pinScrollToBottomRef.current = true;
          setActiveId(first.id);
          applyModelFromSession(first);
          setChatTools(sessionTools(first));
          if (!first.privateMode && !first.messages.length && (first.messageCount ?? 0) > 0) {
            void loadSessionMessagesIfNeeded(first, { limit: 50 }).then((loaded) => {
              if (gen !== hydrateGenRef.current || activeIdRef.current !== first.id) return;
              setMessages(loaded.messages);
              setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
              if (sessionHasIncompleteTextReply(loaded.messages)) {
                setSessionStreaming(first.id, true);
              }
              patchDefaultTitleFromMessages(first.id, loaded.messages);
              setSessions((prev) => {
                const next = prev.map((row) => (row.id === first.id ? loaded : row));
                sessionsRef.current = next;
                return next;
              });
            });
          } else {
            setMessages(first.messages);
          }
        }
      } catch (err) {
        if (gen !== hydrateGenRef.current) return;
        const localSessions = loadChatSessionsLocal();
        const localFolders = loadChatFoldersLocal();
        if (localSessions.length || localFolders.length) {
          sessionsRef.current = localSessions;
          commitServerListSync(localSessions);
          setSessions(localSessions);
          setFolders(localFolders);
          setHydrateOutcome("ok");
          const first = localSessions[0];
          activeIdRef.current = first.id;
          setActiveId(first.id);
          applyModelFromSession(first);
          setMessages(first.messages);
          setChatTools(sessionTools(first));
        } else {
          setHydrateOutcome("error");
          setChatError(
            err instanceof Error
              ? err.message
              : "Could not load chat history. Try signing out and back in.",
          );
        }
        setChatsHydrated(true);
      }
    })();
  }, []);

  useEffect(() => {
    let debounceTimer: number | undefined;
    const onRefresh = () => {
      if (!chatsHydratedRef.current) return;
      if (debounceTimer) window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(() => {
        debounceTimer = undefined;
        void refreshChatsSince()
          .then((remote) => {
            if (shouldSkipEmptyIncrementalSync(remote)) {
              return;
            }
            const protectedIds = new Set<string>([
              ...Object.keys(streamingSessionsRef.current),
              ...getBackgroundImageSessionIds(),
            ]);
            const merged = mergeRemoteChatSessions(sessionsRef.current, remote.sessions, protectedIds);
            sessionsRef.current = merged;
            setSessions(merged);
          })
          .catch(() => {});
      }, 400);
    };
    window.addEventListener("alpha-router-chat-refresh", onRefresh);
    return () => {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      window.removeEventListener("alpha-router-chat-refresh", onRefresh);
    };
  }, []);

  const loadMoreSessions = useCallback(async () => {
    if (!inSearchMode || sessionsLoadingMore || sessions.length >= sessionsTotal) return;
    setSessionsLoadingMore(true);
    try {
      const remote = await fetchUserChatsFromServer({
        limit: 40,
        offset: sessions.length,
        q: serverSearchQuery || undefined,
      });
      setSessions((prev) => {
        const merged = mergeRemoteChatSessions(prev, remote.sessions);
        sessionsRef.current = merged;
        return merged;
      });
      setSessionsTotal(remote.total ?? sessionsTotal);
    } finally {
      setSessionsLoadingMore(false);
    }
  }, [inSearchMode, sessions.length, sessionsLoadingMore, sessionsTotal, serverSearchQuery]);

  const loadOlderChats = useCallback(
    async (opts?: { append?: boolean }) => {
      const append = !!opts?.append;
      if (append) {
        if (olderLoadingMore || olderLoadedCount >= olderTotal) return;
        setOlderLoadingMore(true);
      } else {
        if (olderLoading) return;
        setOlderLoading(true);
      }
      try {
        const remote = await fetchUserChatsFromServer({
          limit: 40,
          max_activity_ms: sidebarOlderThan3DaysCutoffMs(),
          offset: append ? olderLoadedCount : 0,
        });
        setSessions((prev) => {
          const merged = mergeRemoteChatSessions(prev, remote.sessions);
          sessionsRef.current = merged;
          return merged;
        });
        const loaded = append ? olderLoadedCount + remote.sessions.length : remote.sessions.length;
        setOlderLoadedCount(loaded);
        setOlderTotal(remote.total ?? olderTotal);
      } finally {
        if (append) setOlderLoadingMore(false);
        else setOlderLoading(false);
      }
    },
    [olderLoadedCount, olderLoading, olderLoadingMore, olderTotal],
  );

  const togglePastDaysSection = useCallback(() => {
    setPastDaysExpanded((prev) => !prev);
  }, []);

  const toggleOlderSection = useCallback(() => {
    if (olderExpanded) {
      setOlderExpanded(false);
      return;
    }
    setOlderExpanded(true);
    if (olderLoadedCount === 0 && olderTotal > 0) {
      void loadOlderChats();
    }
  }, [olderExpanded, olderLoadedCount, olderTotal, loadOlderChats]);

  useEffect(() => {
    registerChatSessionsProvider(() => sessionsRef.current);
    return () => registerChatSessionsProvider(() => []);
  }, []);

  useEffect(() => {
    registerPrivateMessagesSync((sessionId, msgs) => {
      updateSessionMessages(sessionId, msgs);
      scheduleServerChatSave({ debounce: false });
    });
    return () => registerPrivateMessagesSync(null);
  }, [updateSessionMessages, scheduleServerChatSave]);

  useEffect(() => {
    registerImmediateChatSync(() => scheduleServerChatSave({ debounce: false }));
  }, [scheduleServerChatSave]);

  useEffect(() => {
    const el = messagesScrollRef.current;
    if (!el) return;
    const onScroll = () => {
      syncScrollPinFromContainer();
      if (el.scrollTop <= 4 && messagesHasOlder && !messagesLoadingOlder && activeIdRef.current) {
        const sid = activeIdRef.current;
        const session = sessionsRef.current.find((s) => s.id === sid);
        if (!session) return;
        setMessagesLoadingOlder(true);
        void loadOlderSessionMessages(session)
          .then(({ session: nextSession, hasMore }) => {
            setMessagesHasOlder(hasMore);
            setSessions((prev) => {
              const updated = prev.map((s) => (s.id === sid ? nextSession : s));
              sessionsRef.current = updated;
              return updated;
            });
            if (sid === activeIdRef.current) setMessages(nextSession.messages);
          })
          .finally(() => setMessagesLoadingOlder(false));
      }
    };
    syncScrollPinFromContainer();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [messagesHasOlder, messagesLoadingOlder, persistSessions, syncScrollPinFromContainer]);

  useEffect(() => {
    return subscribeBackgroundImageUpdates((sessionId) => {
      if (isBackgroundImageRunning(sessionId)) {
        setSessionStreaming(sessionId, true);
        return;
      }
      if (!sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId))) {
        setSessionStreaming(sessionId, false);
      } else {
        queueMicrotask(() => tryDrainPromptQueueRef.current(sessionId));
      }
      const session = sessionsRef.current.find((s) => s.id === sessionId);
      if (session?.privateMode) return;
      if (!abortControllersRef.current[sessionId]) {
        void fetchSessionWithMessages(sessionId)
          .then((remote) => {
            if (!remote?.messages.length) return;
            const local =
              sessionId === activeIdRef.current
                ? messagesRef.current
                : sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
            const merged = mergeChatMessagesPreferLocal(local, remote.messages);
            persistSessions(
              (prev) =>
                prev.map((s) =>
                  s.id === sessionId
                    ? {
                        ...s,
                        messages: merged,
                        revision: remote.revision ?? s.revision,
                        messageCount: Math.max(s.messageCount ?? 0, merged.length),
                      }
                    : s,
                ),
              { debounce: false },
            );
            if (sessionId === activeIdRef.current) {
              setMessages(merged);
            }
            if (!sessionHasInFlightGeneration(merged)) {
              setSessionStreaming(sessionId, false);
            }
          })
          .catch(() => {});
      }
      void syncSessionsFromServer(sessionId);
    });
  }, [syncSessionsFromServer, persistSessions]);

  useEffect(() => {
    const hasNonPrivatePending = sessions.some(
      (s) => sessionHasPendingImage(s.messages) && !s.privateMode,
    );
    if (!hasNonPrivatePending) return;
    const id = window.setInterval(() => {
      const sid = activeIdRef.current;
      if (!sid) return;
      const session = sessionsRef.current.find((s) => s.id === sid);
      if (session?.privateMode) return;
      void syncSessionsFromServer(sid);
    }, 5000);
    return () => window.clearInterval(id);
  }, [sessions, syncSessionsFromServer]);

  useEffect(() => {
    const sid = activeId;
    if (!sid || readOnly) return;
    const session = sessionsRef.current.find((s) => s.id === sid);
    if (!session || session.privateMode) return;
    const msgs = messagesRef.current.length ? messagesRef.current : session.messages;
    if (!sessionHasInFlightGeneration(msgs)) {
      if (streamingSessionsRef.current[sid] && !isBackgroundImageRunning(sid)) {
        setSessionStreaming(sid, false);
      }
      return;
    }
    if (isLocalWorkInFlight(sid)) return;
    if (!isChatSessionOnServer(sid)) return;

    setSessionStreaming(sid, true);
    let cancelled = false;
    const poll = () => {
      if (cancelled || activeIdRef.current !== sid) return;
      if (isLocalWorkInFlight(sid)) return;
      void pollSessionMessagesFromServer(sid, { limit: 50 })
        .then(({ messages: remoteMsgs, revision }) => {
          if (cancelled || activeIdRef.current !== sid) return;
          if (isLocalWorkInFlight(sid)) return;
          const mergedMsgs = preferLocalMessagesOverRemote(sid, remoteMsgs);
          setSessions((prev) => {
            const next = prev.map((s) =>
              s.id === sid
                ? {
                    ...s,
                    messages: mergedMsgs,
                    revision,
                    messageCount: Math.max(s.messageCount ?? 0, mergedMsgs.length),
                  }
                : s,
            );
            sessionsRef.current = next;
            return next;
          });
          if (!isLocalWorkInFlight(sid)) {
            setMessages(mergedMsgs);
          }
          if (!sessionHasInFlightGeneration(mergedMsgs)) {
            setSessionStreaming(sid, false);
          }
        })
        .catch(() => {
          if (cancelled || activeIdRef.current !== sid) return;
          const localMsgs =
            activeIdRef.current === sid
              ? messagesRef.current
              : sessionsRef.current.find((s) => s.id === sid)?.messages ?? [];
          if (!sessionHasInFlightGeneration(localMsgs)) {
            setSessionStreaming(sid, false);
          }
        });
    };
    poll();
    const id = window.setInterval(poll, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeId, readOnly]);

  useEffect(() => {
    if (readOnly) return;
    const queuedSessionIds = Object.entries(promptQueues)
      .filter(([, items]) => items.length > 0)
      .map(([id]) => id);
    if (!queuedSessionIds.length) return;

    const tick = () => {
      for (const sid of queuedSessionIds) {
        tryDrainPromptQueueRef.current(sid);
      }
    };

    tick();
    const id = window.setInterval(tick, 600);
    return () => window.clearInterval(id);
  }, [promptQueues, streamingSessions, readOnly]);

  useEffect(() => {
    const onFocus = () => {
      if (sessions.some((s) => sessionHasPendingImage(s.messages))) {
        void syncSessionsFromServer(activeIdRef.current);
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [sessions, syncSessionsFromServer]);

  useEffect(() => {
    if (hydrateOutcome !== "empty" || !chatsHydrated || activeId || readOnly) return;
    if (!models.length) return;
    const m = resolveNewChatModel(models, undefined, defaultModel);
    const freshTools = copyFreshChatTools();
    const s = createSession(m, "New chat", freshTools);
    persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
    activeIdRef.current = s.id;
    setActiveId(s.id);
    setModel(s.model);
    setMessages([]);
    setChatTools(freshTools);
  }, [hydrateOutcome, chatsHydrated, activeId, readOnly, models, defaultModel, persistSessions]);

  useEffect(() => {
    localStorage.removeItem(STORAGE_KEYS.chatTools);
  }, []);

  useEffect(() => {
    restoringComposerRef.current = true;
    const prev = prevComposerSessionRef.current;
    if (prev && prev !== activeId) {
      syncComposerDraft(
        prev,
        composerInputRef.current,
        composerDirectionRef.current,
        pendingAttachmentsRef.current,
      );
    }
    prevComposerSessionRef.current = activeId;

    if (!activeId) {
      setInput("");
      setInputDirection("ltr");
      setPendingAttachments([]);
      queueMicrotask(() => {
        restoringComposerRef.current = false;
      });
      return;
    }

    const draft = getComposerDraft(activeId);
    if (draft) {
      setInput(draft.text);
      setInputDirection(draft.direction);
      setPendingAttachments(cloneComposerAttachments(draft.attachments));
    } else {
      setInput("");
      setInputDirection("ltr");
      setPendingAttachments([]);
    }
    queueMicrotask(() => {
      restoringComposerRef.current = false;
    });
  }, [activeId]);

  useEffect(() => {
    return () => {
      syncComposerDraft(
        activeIdRef.current,
        composerInputRef.current,
        composerDirectionRef.current,
        pendingAttachmentsRef.current,
      );
    };
  }, []);

  useEffect(() => {
    if (restoringComposerRef.current || !activeId) return;
    syncComposerDraft(activeId, input, inputDirection, pendingAttachments);
  }, [activeId, input, inputDirection, pendingAttachments]);

  useEffect(() => {
    if (!activeId) {
      lastSyncedActiveIdRef.current = null;
      return;
    }
    const s = sessions.find((x) => x.id === activeId);
    if (!s) return;
    const switched = lastSyncedActiveIdRef.current !== activeId;
    lastSyncedActiveIdRef.current = activeId;
    if (!switched) return;
    pinScrollToBottomRef.current = true;
    setShowScrollToBottomBtn(false);
    applyModelFromSession(s);
    setChatTools(sessionTools(s));
    requestAnimationFrame(() => {
      scrollChatToBottom("auto");
      syncScrollPinFromContainer();
    });
    if (!s.privateMode && !s.messages.length && (s.messageCount ?? 0) > 0) {
      void loadSessionMessagesIfNeeded(s, { limit: 50 }).then((loaded) => {
        if (activeIdRef.current !== activeId) return;
        setMessages(loaded.messages);
        setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
          if (sessionHasIncompleteTextReply(loaded.messages)) {
            setSessionStreaming(activeId, true);
          } else if (sessionHasPendingImage(loaded.messages)) {
            setSessionStreaming(activeId, true);
          }
        setSessions((prev) => {
          const next = prev.map((row) => (row.id === activeId ? loaded : row));
          sessionsRef.current = next;
          return next;
        });
      });
    } else {
      setMessages(s.messages);
      setMessagesHasOlder(false);
    }
  }, [activeId, sessions, scrollChatToBottom, persistSessions, syncScrollPinFromContainer]);

  useEffect(() => {
    const id = requestAnimationFrame(() => syncScrollPinFromContainer());
    return () => cancelAnimationFrame(id);
  }, [messages, activeId, syncScrollPinFromContainer]);

  useEffect(() => {
    if (isSessionStreaming) return;
    const behavior: ScrollBehavior = "smooth";
    const id = requestAnimationFrame(() => {
      maybeScrollChatToBottom(behavior);
    });
    return () => cancelAnimationFrame(id);
  }, [messages, isSessionStreaming, maybeScrollChatToBottom]);

  useEffect(() => {
    return () => cancelStreamingMessagesFlush();
  }, [cancelStreamingMessagesFlush]);

  useEffect(() => {
    return () => {
      if (serverSaveTimerRef.current) window.clearTimeout(serverSaveTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  useEffect(() => {
    if (!modelMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(e.target as Node)) {
        setModelMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [modelMenuOpen]);

  useEffect(() => {
    if (!toolsMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (toolsMenuRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest(".cgpt-server-tools-menu")) return;
      setToolsMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [toolsMenuOpen]);

  async function apiMessages(
    history: ChatMessage[],
    forModel?: Model,
    privateMode = false,
  ) {
    const trimmed = historyForModelRequest(history);
    const out: Array<{ role: string; content: string | ApiContentPart[] }> = [];
    for (const m of trimmed) {
      const content = privateMode
        ? await buildApiMessageContentAsync(m.content, forModel)
        : buildApiMessageContent(m.content, forModel);
      out.push({ role: m.role, content });
    }
    return out.filter((m) => hasApiContent(m.content));
  }

  async function chatCompletionBody(
    modelId: string,
    history: ChatMessage[],
    forModel?: Model,
    tools: ChatToolsState = chatTools,
    persist?: {
      sessionId: string;
      userMessage: ChatMessage;
      assistantClientMessageId: string;
    },
    privateMode = false,
  ) {
    const toolsPayload = toolsToApiPayload(tools);
    return {
      model: modelId,
      messages: await apiMessages(history, forModel, privateMode),
      stream: true,
      ...toolsPayload,
      ...(persist
        ? {
            chat_session_id: persist.sessionId,
            persist_chat: true,
            user_message: {
              role: persist.userMessage.role,
              content: persist.userMessage.content,
              clientMessageId: persist.userMessage.clientMessageId,
              sentAt: persist.userMessage.sentAt,
            },
            assistant_client_message_id: persist.assistantClientMessageId,
          }
        : {}),
    };
  }

  function ensureActiveSession(): string | null {
    if (activeIdRef.current) return activeIdRef.current;
    if (readOnly) return null;
    const m = resolveNewChatModel(models, model, defaultModel);
    if (!m) return null;
    const freshTools = copyFreshChatTools();
    const s = createSession(m, "New chat", freshTools);
    persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
    flushSync(() => {
      activeIdRef.current = s.id;
      setActiveId(s.id);
      setModel(m);
      setMessages(s.messages);
      setChatTools(freshTools);
    });
    return s.id;
  }

  function persistActiveComposerDraft(
    overrides?: Partial<{ text: string; direction: TextDirection; attachments: ProcessedAttachment[] }>,
  ) {
    const sid = activeIdRef.current;
    if (!sid) return;
    syncComposerDraft(
      sid,
      overrides?.text ?? composerInputRef.current,
      overrides?.direction ?? composerDirectionRef.current,
      overrides?.attachments ?? pendingAttachmentsRef.current,
    );
  }

  function activateSessionFromRef(id: string) {
    const s = sessionsRef.current.find((x) => x.id === id);
    if (!s) return;
    activeIdRef.current = id;
    pinScrollToBottomRef.current = true;
    setActiveId(id);
    applyModelFromSession(s);
    setChatTools(sessionTools(s));
    setChatError("");
    if (!s.privateMode && !s.messages.length && (s.messageCount ?? 0) > 0) {
      void loadSessionMessagesIfNeeded(s, { limit: 50 }).then((loaded) => {
        if (activeIdRef.current !== id) return;
        setMessages(loaded.messages);
        setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
        patchDefaultTitleFromMessages(id, loaded.messages);
        setSessions((prev) => {
          const next = prev.map((row) => (row.id === id ? loaded : row));
          sessionsRef.current = next;
          return next;
        });
      });
    } else {
      setMessages(s.messages);
      setMessagesHasOlder(false);
    }
    requestAnimationFrame(() => scrollChatToBottom("auto"));
  }

  function selectSession(id: string) {
    activateSessionFromRef(id);
  }

  function startNewChat() {
    if (readOnly) return;
    const m = resolveNewChatModel(models, model, defaultModel);
    if (!m) {
      setChatError("No model available.");
      return;
    }
    const freshTools = copyFreshChatTools();
    const s = createSession(m, "New chat", freshTools);
    persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
    activeIdRef.current = s.id;
    pinScrollToBottomRef.current = true;
    setActiveId(s.id);
    setModel(m);
    setMessages([]);
    setChatTools(freshTools);
    setToolsMenuOpen(false);
    setChatError("");
    requestAnimationFrame(() => scrollChatToBottom("auto"));
  }

  async function removeChatSession(id: string): Promise<void> {
    stopBackgroundImageGeneration(id);
    clearComposerDraft(id);
    const controller = abortControllersRef.current[id];
    if (controller) {
      controller.abort();
      delete abortControllersRef.current[id];
    }
    setSessionStreaming(id, false);
    if (!sessionPrivateMode(id) && isChatSessionOnServer(id)) {
      void cancelStreamingReplyOnServer(id).catch(() => {});
    }

    const deletedSession = sessionsRef.current.find((s) => s.id === id);
    markPendingDelete(id);

    const prevActiveId = activeId;
    persistSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      if (activeId === id) {
        if (next.length) {
          const first = next[0];
          queueMicrotask(() => selectSession(first.id));
        } else if (models.length) {
          const s = createSession(resolveNewChatModel(models, undefined, defaultModel));
          queueMicrotask(() => {
            setActiveId(s.id);
            setModel(s.model);
            setMessages([]);
            setChatTools(copyFreshChatTools());
          });
          return [s];
        } else {
          setActiveId(null);
          setMessages([]);
        }
      }
      return next;
    });

    if (sessionPrivateMode(id)) return;

    try {
      await deleteChatSessionOnServer(id);
    } catch (err) {
      if (deletedSession) {
        persistSessions((prev) => {
          if (prev.some((s) => s.id === id)) return prev;
          const restored = [deletedSession, ...prev].sort((a, b) => b.updatedAt - a.updatedAt);
          return restored;
        });
        if (prevActiveId === id) {
          queueMicrotask(() => selectSession(id));
        }
      }
      setChatError(err instanceof Error ? err.message : "Could not delete chat.");
    }
  }

  async function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (readOnly) return;
    await removeChatSession(id);
  }

  function startRenameSession(session: ChatSession, e: React.MouseEvent) {
    e.stopPropagation();
    if (readOnly) return;
    setRenamingSessionId(session.id);
    setRenamingTitle(session.title || "");
  }

  function commitRenameSession() {
    const sid = renamingSessionId;
    if (!sid) return;
    const title = renamingTitle.trim();
    if (!title) {
      setRenamingSessionId(null);
      setRenamingTitle("");
      return;
    }
    persistSessions((prev) =>
      prev.map((s) =>
        s.id === sid
          ? {
              ...s,
              title,
              titleLocked: true,
              updatedAt: Date.now(),
            }
          : s,
      ),
    );
    setRenamingSessionId(null);
    setRenamingTitle("");
  }

  function addFolder() {
    if (readOnly) return;
    const name = newFolderName.trim();
    if (!name) return;
    const f = createFolder(name);
    persistFolders((prev) => [f, ...prev]);
    setCollapsedFolders((prev) => ({ ...prev, [f.id]: false }));
    setNewFolderName("");
  }

  function toggleFolderCollapse(folderId: string) {
    setCollapsedFolders((prev) => ({ ...prev, [folderId]: !prev[folderId] }));
  }

  function startRenameFolder(folder: ChatFolder, e?: React.MouseEvent) {
    e?.stopPropagation();
    setRenamingFolderId(folder.id);
    setRenamingFolderName(folder.name || "");
  }

  function commitRenameFolder() {
    const fid = renamingFolderId;
    if (!fid) return;
    const name = renamingFolderName.trim();
    if (!name) {
      setRenamingFolderId(null);
      setRenamingFolderName("");
      return;
    }
    persistFolders((prev) =>
      prev.map((f) => (f.id === fid ? { ...f, name, updatedAt: Date.now() } : f)),
    );
    setRenamingFolderId(null);
    setRenamingFolderName("");
  }

  function cleanupFolderState(folderId: string) {
    setCollapsedFolders((prev) => {
      if (!(folderId in prev)) return prev;
      const next = { ...prev };
      delete next[folderId];
      return next;
    });
    if (dropFolderId === folderId) setDropFolderId(null);
    if (renamingFolderId === folderId) {
      setRenamingFolderId(null);
      setRenamingFolderName("");
    }
  }

  function removeFolderRecord(folderId: string) {
    persistFolders((prev) => prev.filter((f) => f.id !== folderId));
    cleanupFolderState(folderId);
  }

  function deleteFolderKeepChats(folderId: string) {
    removeFolderRecord(folderId);
    persistSessions((prev) =>
      prev.map((s) => (s.folderId === folderId ? { ...s, folderId: null } : s)),
    );
  }

  function deleteFolderAndChats(folderId: string, chatsInFolder: ChatSession[]) {
    const removedIds = new Set(chatsInFolder.map((c) => c.id));
    removedIds.forEach((sessionId) => clearComposerDraft(sessionId));
    removeFolderRecord(folderId);
    persistSessions((prev) => {
      let next = prev.filter((s) => !removedIds.has(s.id));
      if (activeId && removedIds.has(activeId)) {
        if (next.length) {
          queueMicrotask(() => selectSession(next[0].id));
        } else if (models.length) {
          const s = createSession(resolveNewChatModel(models, undefined, defaultModel));
          next = [s, ...next];
          queueMicrotask(() => {
            activeIdRef.current = s.id;
            setActiveId(s.id);
            setModel(s.model);
            setMessages([]);
            setChatTools(copyFreshChatTools());
          });
        } else {
          activeIdRef.current = null;
          queueMicrotask(() => {
            setActiveId(null);
            setMessages([]);
          });
        }
      }
      return next;
    });
  }

  async function confirmDeleteFolder(folder: ChatFolder) {
    const chatsInFolder = sessions.filter((s) => s.folderId === folder.id);
    const proceed = await confirm({
      title: "Delete folder",
      message:
        chatsInFolder.length > 0
          ? `Delete folder "${folder.name}"? It contains ${chatsInFolder.length} chat(s).`
          : `Delete folder "${folder.name}"?`,
      confirmLabel: chatsInFolder.length > 0 ? "Continue" : "Delete",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!proceed) return;

    if (chatsInFolder.length === 0) {
      removeFolderRecord(folder.id);
      return;
    }

    const choice = await confirm({
      title: "Chats in this folder",
      message: `Also delete the ${chatsInFolder.length} chat(s) in "${folder.name}"?`,
      confirmLabel: "Yes, delete chats",
      secondaryLabel: "Delete folder, keep chats",
      cancelLabel: "Cancel",
      danger: true,
    });

    if (choice === false) return;
    if (choice === "secondary") {
      deleteFolderKeepChats(folder.id);
      return;
    }
    deleteFolderAndChats(folder.id, chatsInFolder);
  }

  function setFolderColor(folderId: string, color: string | null) {
    persistFolders((prev) =>
      prev.map((f) => (f.id === folderId ? { ...f, color: color || null, updatedAt: Date.now() } : f)),
    );
  }

  function moveSessionToFolder(sessionId: string, folderId: string | null) {
    persistSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, folderId } : s)),
    );
    setDropFolderId(null);
  }

  function sessionDisplayTitle(s: ChatSession): string {
    if (!isDefaultChatTitle(s.title)) return s.title;
    const derived = sessionTitleFromMessages(s.messages);
    return !isDefaultChatTitle(derived) ? derived : s.title || DEFAULT_CHAT_TITLE;
  }

  function renderSessionRow(s: ChatSession, wrap: "li" | "div" = "li") {
    const isRenaming = renamingSessionId === s.id;
    const inner = (
      <>
        {isRenaming ? (
          <form
            className="cgpt-history-rename"
            onSubmit={(e) => {
              e.preventDefault();
              commitRenameSession();
            }}
          >
            <input
              value={renamingTitle}
              onChange={(e) => setRenamingTitle(e.target.value)}
              onBlur={commitRenameSession}
              autoFocus
            />
          </form>
        ) : (
          <button
            type="button"
            className={`cgpt-history-item${s.id === activeId ? " active" : ""}${streamingSessions[s.id] || isBackgroundImageRunning(s.id) ? " is-streaming" : ""}`}
            onClick={() => selectSession(s.id)}
          >
            {s.privateMode ? (
              <span className="cgpt-history-item__lock" title="Private Mode" aria-hidden>
                <PrivateModeLockIcon className="cgpt-history-item__lock-icon" size={14} />
              </span>
            ) : null}
            {streamingSessions[s.id] || isBackgroundImageRunning(s.id) ? (
              <span className="cgpt-history-item__busy" title="Generating…" aria-hidden />
            ) : null}
            {sessionDisplayTitle(s)}
          </button>
        )}
        {!readOnly && (
          <>
            <button
              type="button"
              className="cgpt-history-rename-btn"
              onClick={(e) => startRenameSession(s, e)}
              aria-label="Rename chat"
              title="Rename"
            >
              ✎
            </button>
            <button
              type="button"
              className="cgpt-history-delete"
              onClick={(e) => deleteSession(s.id, e)}
              aria-label="Delete chat"
            >
              ×
            </button>
          </>
        )}
      </>
    );
    const dragProps = {
      draggable: !readOnly,
      onDragStart: () => {
        if (readOnly) return;
        setDraggingSessionId(s.id);
      },
      onDragEnd: () => {
        setDraggingSessionId(null);
        setDropFolderId(null);
      },
    };
    if (wrap === "div") {
      return (
        <div key={s.id} className="cgpt-history-row" {...dragProps}>
          {inner}
        </div>
      );
    }
    return (
      <li key={s.id} {...dragProps}>
        {inner}
      </li>
    );
  }

  function pickModel(id: string) {
    setModel(id);
    setModelMenuOpen(false);
    setModelSearch("");
    setChatError("");
    const sid = activeIdRef.current || ensureActiveSession();
    if (sid) {
      persistSessions(
        (prev) =>
          prev.map((s) => (s.id === sid ? { ...s, model: id } : s)),
        { debounce: false, metadataSessionIds: [sid] },
      );
      if (!sessionPrivateMode(sid)) {
        void pushSessionMetadataToServer(sid).catch(() => {});
      }
    }
  }

  function resolveImageGenerationModel(candidate: Model): Model {
    if (isAutoRouterModel(candidate)) return candidate;
    const resolved = resolveConcreteImageModel(models, candidate);
    if (resolved.id !== candidate.id) pickModel(resolved.id);
    return resolved;
  }

  function willRoutePromptToImageGeneration(
    userContent: string,
    tools: ChatToolsState,
    primaryModel: Model,
    priorMessages: ChatMessage[],
  ): boolean {
    const turnModel = tools.imageGeneration
      ? resolveImageGenerationModel(primaryModel)
      : primaryModel;
    return shouldRouteToImageGeneration(
      userContent,
      tools.imageGeneration,
      modelSupportsTextToImage(turnModel, models),
      modelSupportsImageToImage(turnModel, models),
      lastAssistantImageUrl(priorMessages),
    );
  }

  function setAsDefaultModel(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    setDefaultModel(id);
    serverDefaultModelRef.current = id;
    void saveDefaultModelToServer(id)
      .then((saved) => {
        const next = saved || id;
        setDefaultModel(next);
        serverDefaultModelRef.current = next;
      })
      .catch(() => {
        setChatError("Could not save default model. Try again.");
      });
  }

  async function streamTextCompletion(
    modelId: string,
    history: ChatMessage[],
    forModel: Model | undefined,
    signal: AbortSignal,
    onPartial: (text: string) => void,
    tools: ChatToolsState = chatTools,
    persist?: {
      sessionId: string;
      userMessage: ChatMessage;
      assistantClientMessageId: string;
    },
    privateMode = false,
  ): Promise<string> {
    const res = await authFetch("/api/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(
        await chatCompletionBody(modelId, history, forModel, tools, persist, privateMode),
      ),
      signal,
    });
    if (!res.ok) throw new Error(parseApiError(await res.text(), res.status));

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response stream");

    const decoder = new TextDecoder();
    let assistant = "";
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") continue;
        try {
          const json = JSON.parse(payload);
          if (json.error) {
            const errMsg =
              typeof json.error === "string"
                ? json.error
                : json.error?.message || JSON.stringify(json.error);
            throw new Error(errMsg);
          }
          const delta = json.choices?.[0]?.delta?.content;
          if (delta) {
            assistant += delta;
            onPartial(assistant);
          }
        } catch (err) {
          if (err instanceof SyntaxError) continue;
          throw err;
        }
      }
    }
    return assistant;
  }

  type TextTurnPersistCtx = {
    userMessage: ChatMessage;
    assistantClientMessageId: string;
  };

  function historyForCompletionApi(history: ChatMessage[]): ChatMessage[] {
    const last = history.at(-1);
    if (last?.role === "assistant" && !(last.content || "").trim()) {
      return history.slice(0, -1);
    }
    return history;
  }

  async function syncTextTurnToServer(
    sessionId: string,
    turnMessages: ChatMessage[],
  ): Promise<void> {
    if (sessionPrivateMode(sessionId)) return;
    // The backend ChatCompletionPersister owns the assistant row (append + stream
    // PATCH + finalize). Pushing a trailing empty assistant placeholder here would
    // race that writer and could blank out streamed content, so drop it.
    const tail = turnMessages.at(-1);
    const toSync =
      tail?.role === "assistant" && !(tail.content || "").trim()
        ? turnMessages.slice(0, -1)
        : turnMessages;
    if (!toSync.length) return;
    await syncSessionMessagesToServer(sessionId, toSync);
    patchDefaultTitleFromMessages(sessionId, toSync);
  }

  async function runChatTurn(
    sid: string,
    historyWithUser: ChatMessage[],
    primaryModel: Model,
    controller: AbortController,
    turnBaseCount: number,
    persistCtx?: TextTurnPersistCtx,
  ) {
    const emptyReply =
      "No response from model. Check Connections and enable the model in Admin → Models.";
    const turnSession = sessionsRef.current.find((s) => s.id === sid);
    const turnTools =
      sid === activeIdRef.current ? chatToolsRef.current : sessionTools(turnSession);

    const historyForApi = historyForCompletionApi(historyWithUser);
    const scopedHistory = historyForModelRequest(historyForApi);

    const userContent =
      scopedHistory.filter((m) => m.role === "user").at(-1)?.content || "";
    const promptText = promptTextFromUserContent(userContent);
    const usePriorImage = promptImpliesImageEdit(promptText);
    const priorImage = usePriorImage
      ? lastAssistantImageUrl(scopedHistory.slice(0, -1))
      : undefined;
    const referenceImage = await resolveImageGenerationReferenceAsync(
      userContent,
      scopedHistory.slice(0, -1),
      usePriorImage,
    );
    const turnModel = turnTools.imageGeneration
      ? resolveImageGenerationModel(primaryModel)
      : primaryModel;

    if (
      shouldRouteToImageGeneration(
        userContent,
        turnTools.imageGeneration,
        modelSupportsTextToImage(turnModel, models),
        modelSupportsImageToImage(turnModel, models),
        priorImage,
      )
    ) {
      if (referenceImage && !modelSupportsImageToImage(turnModel, models)) {
        const errMsgs: ChatMessage[] = [
          ...historyForApi,
          {
            role: "assistant",
            content:
              "Error: The selected model does not support image-to-image. Choose a model that accepts image input (e.g. Gemini image or FLUX Kontext).",
            receivedAt: Date.now(),
          },
        ];
        flushSync(() => applyMessages(sid, errMsgs));
        if (!sessionPrivateMode(sid)) {
          void persistChatMessages(sid, errMsgs.slice(-1)).catch((err) =>
            reportSyncError(err, sid),
          );
        }
        return;
      }
      const pendingMsgs: ChatMessage[] = [
        ...historyForApi,
        { role: "assistant", content: IMAGE_PENDING_MARKER, clientMessageId: newClientMessageId() },
      ];
      flushSync(() => updateSessionMessages(sid, pendingMsgs));
      try {
        await runBackgroundImageGeneration({
          sessionId: sid,
          historyWithUser: scopedHistory,
          localMessageBase: historyForApi,
          prompt: promptText,
          modelId: turnModel.id,
          privateMode: sessionPrivateMode(sid),
          referenceImage,
          imageAspectPreset: turnTools.imageAspectRatio,
          imageCustomAspectRatio: turnTools.imageCustomAspectRatio,
          imageCustomSize: turnTools.imageCustomSize,
        });
        setChatError("");
        if (sessionPrivateMode(sid)) {
          const local = sessionsRef.current.find((s) => s.id === sid);
          if (local) {
            deferSessionTitle(sid, turnModel.id, local.messages);
          }
        } else {
          const session = await fetchSessionWithMessages(sid);
          if (session) {
            const local = sessionsRef.current.find((s) => s.id === sid);
            const msgs =
              session.messages.length > 0
                ? session.messages
                : local?.messages.length
                  ? local.messages
                  : session.messages;
            flushSync(() => updateSessionMessages(sid, msgs));
            deferSessionTitle(sid, turnModel.id, msgs);
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (sessionPrivateMode(sid)) {
          const local = sessionsRef.current.find((s) => s.id === sid);
          if (local) {
            void scheduleSessionTitle(sid, turnModel.id, local.messages);
          }
        } else {
          const session = await fetchSessionWithMessages(sid);
          if (session) {
            const local = sessionsRef.current.find((s) => s.id === sid);
            const msgs =
              session.messages.length > 0
                ? session.messages
                : local?.messages.length
                  ? local.messages
                  : session.messages;
            flushSync(() => updateSessionMessages(sid, msgs));
            void scheduleSessionTitle(sid, turnModel.id, msgs);
          }
        }
      }
      return;
    }

    const assistantClientMessageId =
      persistCtx?.assistantClientMessageId ?? newClientMessageId();
    const userMsg =
      persistCtx?.userMessage ??
      historyForApi.filter((m) => m.role === "user").at(-1) ??
      historyWithUser.at(-1)!;

    if (!persistCtx) {
      const placeholder: ChatMessage = {
        role: "assistant",
        content: "",
        clientMessageId: assistantClientMessageId,
        modelId: primaryModel.id,
        modelName: primaryModel.name,
      };
      const withPlaceholder = [...historyForApi, placeholder];
      applyMessages(sid, withPlaceholder);
      if (!sessionPrivateMode(sid)) {
        await syncTextTurnToServer(sid, withPlaceholder);
      }
    }

    const useServerPersist = !sessionPrivateMode(sid);
    const assistant = await streamTextCompletion(
      primaryModel.id,
      historyForApi,
      primaryModel,
      controller.signal,
      (content) => {
        if (turnPhasesRef.current[sid] !== "writing") {
          setTurnPhase(sid, "writing");
        }
        applyMessagesStreaming(sid, [
          ...historyForApi,
          {
            role: "assistant",
            content,
            clientMessageId: assistantClientMessageId,
            modelId: primaryModel.id,
            modelName: primaryModel.name,
          },
        ]);
      },
      turnTools,
      useServerPersist
        ? {
            sessionId: sid,
            userMessage: userMsg,
            assistantClientMessageId,
          }
        : undefined,
      sessionPrivateMode(sid),
    );
    const receivedAt = Date.now();
    const finalContent = assistant.trim() ? assistant : emptyReply;
    const finalMsgs: ChatMessage[] = [
      ...historyForApi,
      {
        role: "assistant",
        content: finalContent,
        receivedAt,
        clientMessageId: assistantClientMessageId,
        modelId: primaryModel.id,
        modelName: primaryModel.name,
      },
    ];
    applyMessages(sid, finalMsgs);
    if (useServerPersist) {
      void fetchSessionWithMessages(sid).then((remote) => {
        if (!remote?.messages.length) return;
        if (activeIdRef.current !== sid && !sessionsRef.current.some((s) => s.id === sid)) return;
        const local = getLocalMessagesForSession(sid);
        const reconciled = mergeChatMessagesPreferLocal(
          local,
          remote.messages,
          isLocalWorkInFlight(sid),
        );
        applyMessages(sid, reconciled);
      });
    }
    patchDefaultTitleFromMessages(sid, finalMsgs);
    void scheduleSessionTitle(sid, primaryModel.id, finalMsgs);
  }

  async function togglePrivateMode(next: boolean) {
    const sid = activeIdRef.current;
    if (!sid) return;
    if (next) {
      setToolsMenuOpen(false);
      const firstConfirmed = await confirm({
        title: "Enable Private Mode?",
        message:
          "Messages and media will be stored only in this browser. Private Mode cannot be turned off for this chat.",
        emphasize: "Private Mode cannot be turned off for this chat",
        confirmLabel: "Continue",
        cancelLabel: "Cancel",
      });
      if (!firstConfirmed) return;
      const finalConfirmed = await confirm({
        title: "Final confirmation",
        message:
          "This change is permanent. This chat will be deleted when you log out or clear browser data.",
        emphasize: "deleted",
        emphasizeDanger: true,
        confirmLabel: "Enable Permanently",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (!finalConfirmed) return;
      persistSessions(
        (prev) =>
          prev.map((s) =>
            s.id === sid ? { ...s, privateMode: true, updatedAt: Date.now() } : s,
          ),
        { debounce: false },
      );
      return;
    }

    // Private Mode is intentionally irreversible for an existing chat.
    return;
  }

  function updateChatTools(next: ChatToolsState) {
    setChatTools(next);
    const sid = activeIdRef.current;
    if (sid) {
      persistSessions(
        (prev) =>
          prev.map((s) =>
            s.id === sid ? { ...s, tools: { ...next }, toolsTouched: true, updatedAt: Date.now() } : s,
          ),
        { debounce: false, metadataSessionIds: [sid] },
      );
      if (!sessionPrivateMode(sid)) {
        void pushSessionMetadataToServer(sid).catch(() => {});
      }
    }
    if (next.imageGeneration) {
      const current = models.find((m) => m.id === model);
      if (!current || !modelSupportsImages(current, models)) {
        const fallback = findImageGenerationFallbackModel(models);
        if (fallback) pickModel(fallback.id);
      }
    }
  }

  function sessionMessagesForQueue(sessionId: string): ChatMessage[] {
    const session = sessionsRef.current.find((s) => s.id === sessionId);
    if (session) return session.messages;
    if (sessionId === activeIdRef.current) return messagesRef.current;
    return [];
  }

  function canProcessPromptQueue(sessionId: string): boolean {
    if (abortControllersRef.current[sessionId]) return false;
    if (isBackgroundImageRunning(sessionId)) return false;
    if (streamingSessionsRef.current[sessionId]) return false;
    return !sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
  }

  function isSessionBusyForSend(sessionId: string): boolean {
    if (abortControllersRef.current[sessionId]) return true;
    if (isBackgroundImageRunning(sessionId)) return true;
    if (streamingSessionsRef.current[sessionId]) return true;
    return sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
  }

  function clearStaleStreamingFlag(sessionId: string): void {
    if (!streamingSessionsRef.current[sessionId]) return;
    if (abortControllersRef.current[sessionId]) return;
    if (isBackgroundImageRunning(sessionId)) return;
    if (sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId))) return;
    setSessionStreaming(sessionId, false);
  }

  function tryDrainPromptQueue(sessionId: string): void {
    if (!promptQueuesRef.current[sessionId]?.length) return;
    clearStaleStreamingFlag(sessionId);
    if (!canProcessPromptQueue(sessionId)) return;
    void drainSessionQueue(sessionId);
  }

  function setTurnPhase(sessionId: string, phase: TurnPhase | undefined) {
    const next = { ...turnPhasesRef.current };
    if (phase) {
      next[sessionId] = phase;
    } else {
      delete next[sessionId];
    }
    turnPhasesRef.current = next;
    setTurnPhases({ ...next });
  }

  function setSessionStreaming(sessionId: string, value: boolean) {
    const next = { ...streamingSessionsRef.current };
    if (value) {
      if (next[sessionId]) return;
      next[sessionId] = true;
      streamingSessionsRef.current = next;
      setStreamingSessions(next);
      return;
    }
    if (next[sessionId]) {
      delete next[sessionId];
    }
    setTurnPhase(sessionId, undefined);
    streamingSessionsRef.current = next;
    setStreamingSessions(next);
    queueMicrotask(() => tryDrainPromptQueue(sessionId));
  }

  async function copyMessageContent(content: string, key: string) {
    const text = displayTextForMessage(content || "").trim();
    if (!text) return;
    const ok = await copyTextToClipboard(text);
    if (!ok) {
      setChatError("Copy failed. Please try again.");
      return;
    }
    setCopiedMessageKey(key);
    window.setTimeout(() => setCopiedMessageKey((prev) => (prev === key ? null : prev)), 1400);
  }

  async function rateAssistantMessage(index: number, rating: -1 | 1) {
    const sid = activeIdRef.current;
    const current = messagesRef.current[index];
    if (!sid || !current?.id || current.role !== "assistant") return;
    const previous = current.feedback;
    const nextRating: -1 | 0 | 1 = previous?.rating === rating ? 0 : rating;
    const applyFeedback = (feedback: ChatMessage["feedback"]) => {
      const nextMessages = messagesRef.current.map((message, messageIndex) =>
        messageIndex === index ? { ...message, feedback } : message,
      );
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setSessions((prev) => {
        const next = prev.map((session) =>
          session.id === sid ? { ...session, messages: nextMessages } : session,
        );
        sessionsRef.current = next;
        return next;
      });
    };
    applyFeedback(nextRating === 0 ? undefined : { rating: nextRating });
    try {
      const feedback = await setMessageFeedbackOnServer(sid, current.id, nextRating);
      applyFeedback(feedback);
    } catch (error) {
      applyFeedback(previous);
      setChatError(formatApiError(error) || "Could not save feedback.");
    }
  }

  function editUserPrompt(content: string) {
    const attach = readAttachmentMessage(content);
    if (attach) {
      const text = attach.userText || "";
      const dir = inputDirectionForText(text, text.length);
      setInput(text);
      setInputDirection(dir);
      persistActiveComposerDraft({ text, direction: dir });
      textareaRef.current?.focus();
      return;
    }
    const next = content || "";
    const dir = inputDirectionForText(next, next.length);
    setInput(next);
    setInputDirection(dir);
    persistActiveComposerDraft({ text: next, direction: dir });
    textareaRef.current?.focus();
  }

  function deleteUserPromptAt(index: number) {
    const sid = activeIdRef.current;
    if (!sid) return;
    const current = getSessionMessages(sid);
    if (streamingSessions[sid] || sessionHasInFlightGeneration(current)) {
      setChatError("Stop generation before deleting a prompt.");
      return;
    }
    if (index < 0 || index >= current.length) return;
    const target = current[index];
    if (!target || target.role !== "user") return;
    const next = removePromptThreadFromMessages(current, target, index);
    if (!next) return;
    clearSessionMessageSyncQueue(sid);
    if (next.length === 0) {
      void removeChatSession(sid);
      return;
    }
    updateSessionMessages(sid, next);
    if (sessionPrivateMode(sid)) return;
    void replaceChatSessionMessagesOnServer(sid, next, {
      reconcile: (remote) => removePromptThreadFromMessages(remote, target),
    })
      .then((polled) => {
        setChatError("");
        persistSessions((prev) => {
          const updated = prev.map((s) =>
            s.id === sid
              ? {
                  ...s,
                  messages: polled.messages,
                  revision: polled.revision,
                  messageCount: polled.messages.length,
                  updatedAt: Date.now(),
                }
              : s,
          );
          sessionsRef.current = updated;
          return updated;
        });
        if (activeIdRef.current === sid) {
          setMessages(polled.messages);
        }
      })
      .catch((err) => {
        reportUserFacingApiError(err);
        void syncSessionsFromServer(sid);
      });
  }

  function parseApiError(raw: string, status: number) {
    try {
      const j = JSON.parse(raw);
      return j.detail || j.message || raw;
    } catch {
      return raw || `Request failed (${status})`;
    }
  }

  function stopGenerating(sessionId?: string | null) {
    const sid = sessionId || activeIdRef.current;
    if (!sid) return;

    stopBackgroundImageGeneration(sid);
    const controller = abortControllersRef.current[sid];
    if (controller) {
      controller.abort();
      delete abortControllersRef.current[sid];
    }

    const localMsgs = getSessionMessages(sid);
    const last = localMsgs.at(-1);
    if (localMsgs.some((m) => m.content === IMAGE_PENDING_MARKER)) {
      applyMessages(sid, buildStoppedImageMessages(localMsgs));
    } else if (last?.role === "assistant" && !last.receivedAt) {
      const content = (last.content || "").trim() ? last.content : "Generation stopped.";
      applyMessages(sid, [
        ...localMsgs.slice(0, -1),
        { ...last, content, receivedAt: Date.now() },
      ]);
    }

    setSessionStreaming(sid, false);
    setTurnPhase(sid, undefined);

    if (!sessionPrivateMode(sid) && isChatSessionOnServer(sid)) {
      const hadPendingImage = localMsgs.some((m) => m.content === IMAGE_PENDING_MARKER);
      const refreshAfterStop = () => {
        void pollSessionMessagesFromServer(sid, { limit: 50 })
          .then(({ messages: remoteMsgs, revision }) => {
            if (activeIdRef.current !== sid) return;
            const mergedMsgs = preferLocalMessagesOverRemote(sid, remoteMsgs);
            setSessions((prev) => {
              const next = prev.map((s) =>
                s.id === sid
                  ? {
                      ...s,
                      messages: mergedMsgs,
                      revision,
                      messageCount: Math.max(s.messageCount ?? 0, mergedMsgs.length),
                    }
                  : s,
              );
              sessionsRef.current = next;
              return next;
            });
            if (activeIdRef.current === sid) setMessages(mergedMsgs);
            if (!sessionHasInFlightGeneration(mergedMsgs)) {
              setSessionStreaming(sid, false);
            }
          })
          .catch(() => {});
      };
      void cancelStreamingReplyOnServer(sid)
        .catch((err) => reportSyncError(err, sid))
        .finally(() => {
          if (hadPendingImage) {
            void patchLastSessionMessageOnServer(sid, "Image generation stopped.", {
              receivedAt: Date.now(),
            })
              .catch(() => {})
              .finally(refreshAfterStop);
          } else {
            refreshAfterStop();
          }
        });
    }
  }

  function setSessionQueue(sessionId: string, items: QueuedPrompt[]) {
    promptQueuesRef.current = { ...promptQueuesRef.current, [sessionId]: items };
    setPromptQueues((prev) => ({ ...prev, [sessionId]: items }));
  }

  function enqueuePrompt(sessionId: string, text: string, attachments: ProcessedAttachment[]) {
    const item: QueuedPrompt = {
      id: newQueueId(),
      text: text.trim(),
      attachments: cloneProcessedAttachments(attachments),
    };
    const prev = promptQueuesRef.current[sessionId] || [];
    setSessionQueue(sessionId, [...prev, item]);
    queueMicrotask(() => tryDrainPromptQueueRef.current(sessionId));
  }

  function removeQueuedPrompt(sessionId: string, itemId: string) {
    const prev = promptQueuesRef.current[sessionId] || [];
    setSessionQueue(
      sessionId,
      prev.filter((q) => q.id !== itemId),
    );
  }

  function editQueuedPrompt(item: QueuedPrompt) {
    const sid = activeIdRef.current;
    if (!sid) return;
    const dir = inputDirectionForText(item.text, item.text.length);
    const attachments = item.attachments.map((a) => ({ ...a }));
    setInput(item.text);
    setInputDirection(dir);
    setPendingAttachments(attachments);
    persistActiveComposerDraft({ text: item.text, direction: dir, attachments });
    removeQueuedPrompt(sid, item.id);
    textareaRef.current?.focus();
  }

  function getSessionMessages(sessionId: string): ChatMessage[] {
    return sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
  }

  async function executePromptTurn(
    sessionId: string,
    userText: string,
    attachments: ProcessedAttachment[],
  ) {
    if (!userText.trim() && !attachments.length) return;

    const validModel =
      models.find((m) => m.id === model) ||
      models.find((m) => m.external_id === model) ||
      models[0];
    if (!validModel) {
      setChatError("No model available.");
      return;
    }
    if (validModel.id !== model) {
      pickModel(validModel.id);
    }

    const sentAt = Date.now();
    const userMsg: ChatMessage = attachments.length
      ? {
          role: "user",
          content: attachmentMessage({
            userText: userText.trim(),
            attachments,
          }),
          sentAt,
          clientMessageId: newClientMessageId(),
        }
      : { role: "user", content: userText.trim(), sentAt, clientMessageId: newClientMessageId() };
    const prevMsgs = getSessionMessages(sessionId);
    const turnBaseCount = prevMsgs.length;
    const assistantClientMessageId = newClientMessageId();
    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      clientMessageId: assistantClientMessageId,
      modelId: validModel.id,
      modelName: validModel.name,
    };
    const next = [...prevMsgs, userMsg, placeholder];
    pinScrollToBottomRef.current = true;
    const turnSession = sessionsRef.current.find((s) => s.id === sessionId);
    const toolsForTurn =
      sessionId === activeIdRef.current ? chatToolsRef.current : sessionTools(turnSession);
    const willRouteToImage = willRoutePromptToImageGeneration(
      userMsg.content,
      toolsForTurn,
      validModel,
      prevMsgs,
    );
    const controller = new AbortController();
    abortControllersRef.current[sessionId] = controller;
    setSessionStreaming(sessionId, true);
    setTurnPhase(sessionId, toolsForTurn.webSearch ? "searching" : "preparing");
    flushSync(() => {
      if (willRouteToImage) {
        updateSessionMessages(sessionId, next);
      } else {
        applyMessages(sessionId, next);
      }
    });
    scrollAfterNewTurn(sessionId);
    patchDefaultTitleFromMessages(sessionId, next);
    const persistCtx: TextTurnPersistCtx = { userMessage: userMsg, assistantClientMessageId };
    // Server ChatCompletionPersister owns message writes when persist_chat is enabled.
    try {
      await runChatTurn(sessionId, next, validModel, controller, turnBaseCount, persistCtx);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        if (!sessionPrivateMode(sessionId)) {
          void cancelStreamingReplyOnServer(sessionId).catch(() => {});
          void fetchSessionWithMessages(sessionId).then((remote) => {
            if (remote?.messages.length && activeIdRef.current === sessionId) {
              applyMessages(sessionId, remote.messages);
            }
          });
        }
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      const friendly =
        message.includes("network") || message === "Failed to fetch"
          ? "Cannot reach Alpha Router API. Check that Docker is running and hard-refresh (Ctrl+Shift+R)."
          : message;
      const errMsgs: ChatMessage[] = [
        ...next,
        { role: "assistant", content: `Error: ${friendly}`, receivedAt: Date.now() },
      ];
      applyMessages(sessionId, errMsgs);
      if (!sessionPrivateMode(sessionId)) {
        const assistantOnly = errMsgs[errMsgs.length - 1];
        void finalizeAssistantOnServer(sessionId, assistantOnly.content, {
          receivedAt: assistantOnly.receivedAt,
          modelId: validModel.id,
          modelName: validModel.name,
        }).catch((err) => reportSyncError(err, sessionId));
      }
      void scheduleSessionTitle(sessionId, validModel.id, errMsgs);
    } finally {
      delete abortControllersRef.current[sessionId];
      setSessionStreaming(sessionId, false);
    }
  }

  async function drainSessionQueue(sessionId: string): Promise<void> {
    const inFlight = drainPromisesRef.current[sessionId];
    if (inFlight) return inFlight;

    clearStaleStreamingFlag(sessionId);
    if (!canProcessPromptQueue(sessionId)) return;

    const task = (async () => {
      try {
        while (true) {
          if (!canProcessPromptQueue(sessionId)) break;
          const queue = promptQueuesRef.current[sessionId];
          if (!queue?.length) break;
          const [item, ...rest] = queue;
          setSessionQueue(sessionId, rest);
          await executePromptTurn(sessionId, item.text, item.attachments || []);
        }
      } finally {
        delete drainPromisesRef.current[sessionId];
        if (promptQueuesRef.current[sessionId]?.length) {
          queueMicrotask(() => tryDrainPromptQueue(sessionId));
        }
      }
    })();

    drainPromisesRef.current[sessionId] = task;
    return task;
  }

  drainSessionQueueRef.current = drainSessionQueue;
  tryDrainPromptQueueRef.current = tryDrainPromptQueue;

  async function downloadImage(url: string) {
    const triggerDownload = (href: string) => {
      const safeHref = safeBrowserUrl(href, "download");
      if (!safeHref) throw new Error("Blocked unsafe image URL.");
      const a = document.createElement("a");
      a.href = safeHref;
      a.download = "alpha-router-generated-image.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
    };

    try {
      if (isPrivateBlobRef(url)) {
        const blobUrl = await resolvePrivateBlobRef(url);
        triggerDownload(blobUrl);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }
      if (isAlphaRouterMediaFileUrl(url)) {
        const blob = await fetchAuthenticatedMediaBlob(url);
        const blobUrl = URL.createObjectURL(blob);
        triggerDownload(blobUrl);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }
      if (url.startsWith("data:image/")) {
        if (!safeBrowserUrl(url, "image")) throw new Error("Blocked unsafe image data URL.");
        triggerDownload(url);
        return;
      }
      const safeUrl = safeBrowserUrl(url, "download");
      if (!safeUrl) throw new Error("Blocked unsafe image URL.");
      const a = document.createElement("a");
      a.href = safeUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.download = "alpha-router-generated-image.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      setChatError(formatApiError(err));
    }
  }

  async function openImageFullSize(url: string) {
    const openByAnchor = (href: string) => {
      if (!openSafeUrlInNewTab(href, "image")) {
        throw new Error("Blocked unsafe image URL.");
      }
    };

    try {
      if (isPrivateBlobRef(url)) {
        const blobUrl = await resolvePrivateBlobRef(url);
        openByAnchor(blobUrl);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }
      if (isAlphaRouterMediaFileUrl(url)) {
        const blobUrl = await fetchAuthenticatedMediaObjectUrl(url);
        openByAnchor(blobUrl);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }

      if (url.startsWith("data:image/")) {
        if (!safeBrowserUrl(url, "image")) throw new Error("Blocked unsafe image data URL.");
        const [meta, b64] = url.split(",", 2);
        if (!b64) return;
        const mime = meta.match(/^data:(.*?);base64$/)?.[1] || "image/png";
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        const blobUrl = URL.createObjectURL(new Blob([bytes], { type: mime }));
        openByAnchor(blobUrl);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }

      openByAnchor(url);
    } catch (err) {
      setChatError(formatApiError(err));
    }
  }

  async function regenerateImage(msgIndex: number, payload: ImagePayload) {
    const sid = activeIdRef.current;
    if (!sid || streamingSessions[sid]) return;
    const prompt = payload.prompt || "Generate image";
    const modelId =
      (payload.model && payload.model.startsWith("model::") ? payload.model : "") || model;
    if (!modelId) {
      setChatError("No model selected for regenerate.");
      return;
    }
    setChatError("");
    setSessionStreaming(sid, true);
    try {
      await runBackgroundImageGeneration({
        sessionId: sid,
        historyWithUser: historyForModelRequest(messages.slice(0, msgIndex)),
        localMessageBase: messages.slice(0, msgIndex),
        prompt,
        modelId,
        privateMode: sessionPrivateMode(sid),
        referenceImage:
          payload.reference_image || lastAssistantImageUrl(messages.slice(0, msgIndex)),
        imageAspectPreset: sessionTools(sessionsRef.current.find((x) => x.id === sid)).imageAspectRatio,
        imageCustomAspectRatio: sessionTools(sessionsRef.current.find((x) => x.id === sid)).imageCustomAspectRatio,
        imageCustomSize: sessionTools(sessionsRef.current.find((x) => x.id === sid)).imageCustomSize,
        regenerateFrom: {
          aspectRatio: payload.aspectRatio,
          aspectPreset: payload.aspectPreset,
          size: payload.size,
        },
        replaceIndex: msgIndex,
        fullMessages: messages,
      });
      if (!sessionPrivateMode(sid)) {
        await syncSessionsFromServer(sid);
      }
      setChatError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setChatError(message);
      if (!sessionPrivateMode(sid)) {
        await syncSessionsFromServer(sid);
      }
    } finally {
      setSessionStreaming(sid, false);
    }
  }

  async function retryUserPromptAt(index: number) {
    const sid = activeIdRef.current;
    if (!sid) return;
    if (streamingSessions[sid]) {
      setChatError("Stop generation before retry.");
      return;
    }
    const target = messages[index];
    if (!target || target.role !== "user") return;

    const validModel =
      models.find((m) => m.id === model) ||
      models.find((m) => m.external_id === model) ||
      models[0];
    if (!validModel) {
      setChatError("No model available.");
      return;
    }
    if (validModel.id !== model) pickModel(validModel.id);

    const base = messages.slice(0, index);
    const turnBaseCount = base.length;
    const userMsg: ChatMessage = {
      role: "user",
      content: target.content,
      sentAt: Date.now(),
      clientMessageId: newClientMessageId(),
    };
    const assistantClientMessageId = newClientMessageId();
    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      clientMessageId: assistantClientMessageId,
      modelId: validModel.id,
      modelName: validModel.name,
    };
    const next: ChatMessage[] = [...base, userMsg, placeholder];
    pinScrollToBottomRef.current = true;
    const controller = new AbortController();
    abortControllersRef.current[sid] = controller;
    setSessionStreaming(sid, true);
    setChatError("");
    flushSync(() => applyMessages(sid, next));
    scrollAfterNewTurn(sid);
    const persistCtx: TextTurnPersistCtx = { userMessage: userMsg, assistantClientMessageId };

    try {
      await runChatTurn(sid, next, validModel, controller, turnBaseCount, persistCtx);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message = err instanceof Error ? err.message : String(err);
      const friendly =
        message.includes("network") || message === "Failed to fetch"
          ? "Cannot reach Alpha Router API. Check that Docker is running and hard-refresh (Ctrl+Shift+R)."
          : message;
      const errMsgs: ChatMessage[] = [
        ...next,
        { role: "assistant", content: `Error: ${friendly}`, receivedAt: Date.now() },
      ];
      applyMessages(sid, errMsgs);
      if (!sessionPrivateMode(sid)) {
        const assistantOnly = errMsgs[errMsgs.length - 1];
        void finalizeAssistantOnServer(sid, assistantOnly.content, {
          receivedAt: assistantOnly.receivedAt,
          modelId: validModel.id,
          modelName: validModel.name,
        }).catch((err) => reportSyncError(err, sid));
      }
      void scheduleSessionTitle(sid, validModel.id, errMsgs);
    } finally {
      delete abortControllersRef.current[sid];
      setSessionStreaming(sid, false);
    }
  }

  function stopVoiceStream() {
    voiceStreamRef.current?.getTracks().forEach((t) => t.stop());
    voiceStreamRef.current = null;
  }

  async function transcribeVoiceBlob(
    blob: Blob,
    mimeType: string,
    extension: string,
    browserFallback: string,
  ): Promise<string> {
    if (browserFallback.trim()) return browserFallback.trim();
    const sid = activeIdRef.current || ensureActiveSession();
    if (sid && sessionPrivateMode(sid)) {
      throw new Error("No speech detected in Private Mode. Try again or type your message.");
    }
    const fd = new FormData();
    fd.append("file", blob, `voice-${Date.now()}.${extension}`);
    if (sid) fd.append("chat_session_id", sid);
    try {
      const res = await authFetch("/api/chat/voice", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) throw new Error(parseApiError(await res.text(), res.status));
      const data = (await res.json()) as { transcript?: string };
      const text = (data.transcript || "").trim();
      if (text) return text;
    } catch (err) {
      if (browserFallback.trim()) return browserFallback.trim();
      throw err;
    }
    if (browserFallback.trim()) return browserFallback.trim();
    throw new Error("No speech detected. Try again or type your message.");
  }

  async function finishVoiceRecording(
    blob: Blob,
    mimeType: string,
    extension: string,
    browserFallback: string,
  ) {
    if (!model) {
      setChatError("Choose a model below.");
      return;
    }
    setVoiceBusy(true);
    setChatError("");
    try {
      const transcript = await transcribeVoiceBlob(blob, mimeType, extension, browserFallback);
      const next = transcript.trim();
      if (!next) return;
      const base = composerInputRef.current.trim();
      const merged = base ? `${base} ${next}` : next;
      const dir = inputDirectionForText(merged, merged.length);
      setInput(merged);
      setInputDirection(dir);
      persistActiveComposerDraft({ text: merged, direction: dir });
      textareaRef.current?.focus();
    } catch (err) {
      reportUserFacingApiError(err);
    } finally {
      setVoiceBusy(false);
    }
  }

  async function toggleVoiceRecording() {
    if (voiceBusy) return;

    if (voiceRecording && mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      setVoiceRecording(false);
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setChatError("Voice recording is not supported in this browser.");
      return;
    }

    setChatError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceStreamRef.current = stream;
      const { mimeType, extension } = pickVoiceRecordingMime();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      voiceChunksRef.current = [];
      const speech = new BrowserSpeechCapture();
      browserSpeechRef.current = speech;
      speech.start();

      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) voiceChunksRef.current.push(ev.data);
      };
      recorder.onstop = () => {
        const browserText = browserSpeechRef.current?.stop() || "";
        browserSpeechRef.current = null;
        stopVoiceStream();
        const type = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(voiceChunksRef.current, { type });
        voiceChunksRef.current = [];
        mediaRecorderRef.current = null;
        if (blob.size < 200 && !browserText) {
          setChatError("Recording too short. Hold the mic a little longer.");
          return;
        }
        void finishVoiceRecording(blob, type, extension, browserText);
      };
      recorder.onerror = () => {
        browserSpeechRef.current?.stop();
        browserSpeechRef.current = null;
        stopVoiceStream();
        setVoiceRecording(false);
        setChatError("Recording failed. Please try again.");
      };
      mediaRecorderRef.current = recorder;
      recorder.start(250);
      setVoiceRecording(true);
    } catch {
      stopVoiceStream();
      setChatError("Microphone access denied or unavailable.");
    }
  }

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      stopVoiceStream();
    };
  }, []);

  function removePendingAttachment(index: number) {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function openAttachmentPicker() {
    if (attachUploading) return;
    fileInputRef.current?.click();
  }

  async function onAttachmentFilesSelected(list: FileList | null) {
    if (!list?.length) return;
    const sid = ensureActiveSession();
    const files = Array.from(list);
    if (pendingAttachments.length + files.length > MAX_ATTACHMENTS) {
      setChatError(`You can attach up to ${MAX_ATTACHMENTS} files at once.`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setAttachUploading(true);
    setChatError("");
    try {
      if (sid && sessionPrivateMode(sid)) {
        const localAttachments = await processAttachmentFilesLocally(files);
        setPendingAttachments((prev) => [...prev, ...localAttachments].slice(0, MAX_ATTACHMENTS));
      } else {
        for (const file of files) {
          validateAttachmentFile(file);
        }
        const fd = new FormData();
        for (const file of files) fd.append("files", file);
        if (sid) fd.append("chat_session_id", sid);
        const res = await authFetch("/api/chat/attachments/process", {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(parseApiError(await res.text(), res.status));
        const data = (await res.json()) as { attachments: ProcessedAttachment[] };
        setPendingAttachments((prev) => [...prev, ...data.attachments].slice(0, MAX_ATTACHMENTS));
      }
    } catch (err) {
      reportUserFacingApiError(err);
    } finally {
      setAttachUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    if (readOnly) return;
    setChatError("");
    const sid = ensureActiveSession();
    if (!sid) {
      setChatError("Choose a model below.");
      return;
    }
    if ((!input.trim() && !pendingAttachments.length) || !model || attachUploading) {
      return;
    }

    const text = input.trim();
    const attachments = pendingAttachments.map((a) => ({ ...a }));

    setInput("");
    setInputDirection("ltr");
    setPendingAttachments([]);
    clearComposerDraft(sid);

    if (isSessionBusyForSend(sid)) {
      enqueuePrompt(sid, text, attachments);
      return;
    }

    void executePromptTurn(sid, text, attachments);
  }

  async function handleTranslateToEng() {
    const text = input.trim();
    if (!text || translateToEngBusy || !textNeedsEnglishTranslation(text)) return;
    const validModel =
      models.find((m) => m.id === model) ||
      models.find((m) => m.external_id === model) ||
      models[0];
    if (!validModel) return;
    const assistContext = chatTools.imageGeneration ? "image" : "chat";
    setTranslateToEngBusy(true);
    setChatError("");
    try {
      const enhanced = await enhancePrompt(validModel.id, text, "translate", assistContext);
      if (enhanced) {
        const dir = inputDirectionForText(enhanced, enhanced.length);
        setInput(enhanced);
        setInputDirection(dir);
        persistActiveComposerDraft({ text: enhanced, direction: dir });
        requestAnimationFrame(() => textareaRef.current?.focus());
      } else {
        setChatError("Couldn't translate to English. Try again or send as is.");
      }
    } finally {
      setTranslateToEngBusy(false);
    }
  }

  function onComposerInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setInput(value);
    const caret = e.target.selectionStart ?? value.length;
    setInputDirection(inputDirectionForText(value, caret));
  }

  function onComposerSelect(e: React.SyntheticEvent<HTMLTextAreaElement>) {
    const el = e.currentTarget;
    setInputDirection(inputDirectionForText(el.value, el.selectionStart ?? el.value.length));
  }

  async function onComposerPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const clipboard = e.clipboardData;
    if (!clipboard) return;
    const files: File[] = [];
    for (const item of clipboard.items) {
      if (item.kind !== "file") continue;
      const file = item.getAsFile();
      if (file) files.push(file);
    }
    if (!files.length) return;
    e.preventDefault();
    const list = new DataTransfer();
    for (const file of files) list.items.add(file);
    await onAttachmentFilesSelected(list.files);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function isEmptyStreamingAssistant(index: number) {
    if (!isSessionStreaming || messages[index]?.role !== "assistant" || messages[index]?.content) {
      return false;
    }
    let lastUserIdx = -1;
    for (let j = 0; j < messages.length; j += 1) {
      if (messages[j]?.role === "user") lastUserIdx = j;
    }
    return index > lastUserIdx;
  }

  return (
    <div className="cgpt-app">
      <aside className="cgpt-sidebar">
        <div className="cgpt-sidebar-top">
          <button
            type="button"
            className="cgpt-icon-btn cgpt-menu-btn"
            onClick={() => shellMenu?.openAdminMenu()}
            aria-label="Open menu"
            title="Menu"
          >
            ☰
          </button>
          <button type="button" className="cgpt-new-chat" onClick={startNewChat} disabled={readOnly} title={readOnly ? "Read-only account" : undefined}>
            <span className="cgpt-new-chat-icon">+</span>
            New chat
          </button>
        </div>
        <div className="cgpt-sidebar-body">
          <>
            <input
              type="search"
              className="cgpt-history-search"
              placeholder="Search chats…"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
            />
            {!readOnly && (
            <div className="cgpt-folder-create">
              <input
                type="text"
                placeholder="New folder…"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addFolder();
                  }
                }}
              />
              <button type="button" onClick={addFolder} disabled={!newFolderName.trim()}>
                +
              </button>
            </div>
            )}

            <div className="cgpt-folder-group">
              {folders.map((f) => (
                <div
                  key={f.id}
                  className={`cgpt-folder-row${dropFolderId === f.id ? " is-drop-target" : ""}${f.color ? " has-color" : ""}`}
                  style={
                    f.color
                      ? ({ "--folder-accent": f.color } as React.CSSProperties)
                      : undefined
                  }
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDropFolderId(f.id);
                  }}
                  onDragLeave={() => setDropFolderId((prev) => (prev === f.id ? null : prev))}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (draggingSessionId) moveSessionToFolder(draggingSessionId, f.id);
                  }}
                >
                  <div className="cgpt-folder-title">
                    <button
                      type="button"
                      className="cgpt-folder-toggle"
                      onClick={() => toggleFolderCollapse(f.id)}
                      aria-label={collapsedFolders[f.id] ? "Expand folder" : "Collapse folder"}
                      title={collapsedFolders[f.id] ? "Expand" : "Collapse"}
                    >
                      {collapsedFolders[f.id] ? "▸" : "▾"}
                    </button>
                    {renamingFolderId === f.id ? (
                      <form
                        className="cgpt-folder-rename"
                        onSubmit={(e) => {
                          e.preventDefault();
                          commitRenameFolder();
                        }}
                      >
                        <input
                          value={renamingFolderName}
                          onChange={(e) => setRenamingFolderName(e.target.value)}
                          onBlur={commitRenameFolder}
                          autoFocus
                        />
                      </form>
                    ) : (
                      <strong>{f.name}</strong>
                    )}
                    {renamingFolderId !== f.id && !readOnly ? (
                      <div
                        className="cgpt-folder-title-actions"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <RowActionsMenu
                          label="Actions"
                          actions={[
                            { label: "Rename", onClick: () => startRenameFolder(f) },
                            { label: "Change color", onClick: () => setColorPickerFolderId(f.id) },
                            {
                              label: "Delete",
                              onClick: () => void confirmDeleteFolder(f),
                              danger: true,
                            },
                          ]}
                        />
                      </div>
                    ) : null}
                  </div>
                  {!collapsedFolders[f.id] ? (
                    <ul className="cgpt-history cgpt-history-in-folder">
                      {(sessionsByFolder[f.id] || []).map((s) => renderSessionRow(s))}
                      {(sessionsByFolder[f.id] || []).length === 0 && (
                        <li className="cgpt-history-empty">Drop chats here</li>
                      )}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
            {messageSearchHits.length > 0 && historySearch.trim().length >= 2 ? (
              <ul className="cgpt-history cgpt-history-search-hits">
                {messageSearchHits.map((hit) => (
                  <li key={`${hit.sessionId}-${hit.content.slice(0, 24)}`}>
                    <button
                      type="button"
                      className="cgpt-history-item"
                      onClick={() => selectSession(hit.sessionId)}
                    >
                      <span className="cgpt-history-item__subtitle">{hit.sessionTitle}</span>
                      {hit.content.slice(0, 80)}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="cgpt-uncategorized-group">
              {inSearchMode ? (
                filteredSessions.length === 0 ? (
                  <p className="cgpt-history-empty">No conversations</p>
                ) : (
                  <VirtualSidebarList
                    className="cgpt-history-scroll"
                    items={rootSessions.map((s) => ({
                      id: s.id,
                      node: renderSessionRow(s),
                    }))}
                    hasMore={sessions.length < sessionsTotal}
                    loadingMore={sessionsLoadingMore}
                    onLoadMore={() => void loadMoreSessions()}
                  />
                )
              ) : (
                <>
                  {todayRootSessions.length === 0 &&
                  pastDaysRootSessions.length === 0 &&
                  displayOlderCount === 0 ? (
                    <p className="cgpt-history-empty">No conversations</p>
                  ) : (
                    <>
                      {todayRootSessions.length > 0 ? (
                        <>
                          <div className="cgpt-history-section-label">Today</div>
                          <ul className="cgpt-history cgpt-history-scroll">
                            {todayRootSessions.map((s) => (
                              <li key={s.id}>{renderSessionRow(s)}</li>
                            ))}
                          </ul>
                        </>
                      ) : null}
                      {pastDaysRootSessions.length > 0 ? (
                        <div className="cgpt-history-older">
                          <button
                            type="button"
                            className="cgpt-history-older-toggle"
                            onClick={() => togglePastDaysSection()}
                            aria-expanded={pastDaysExpanded}
                          >
                            <span className="cgpt-history-older-chevron">
                              {pastDaysExpanded ? "▾" : "▸"}
                            </span>
                            1–3 days ago ({pastDaysRootSessions.length})
                          </button>
                          {pastDaysExpanded ? (
                            <ul className="cgpt-history cgpt-history-scroll cgpt-history-older-list">
                              {pastDaysRootSessions.map((s) => (
                                <li key={s.id}>{renderSessionRow(s)}</li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      ) : null}
                      {displayOlderCount > 0 ? (
                        <div className="cgpt-history-older">
                          <button
                            type="button"
                            className="cgpt-history-older-toggle"
                            onClick={() => toggleOlderSection()}
                            aria-expanded={olderExpanded}
                          >
                            <span className="cgpt-history-older-chevron">
                              {olderExpanded ? "▾" : "▸"}
                            </span>
                            Older than 3 days ({displayOlderCount})
                          </button>
                          {olderExpanded ? (
                            olderLoading && olderRootSessions.length === 0 ? (
                              <p className="cgpt-history-empty">Loading…</p>
                            ) : (
                              <>
                                <ul className="cgpt-history cgpt-history-scroll cgpt-history-older-list">
                                  {olderRootSessions.map((s) => (
                                    <li key={s.id}>{renderSessionRow(s)}</li>
                                  ))}
                                </ul>
                                {olderLoadedCount < olderTotal ? (
                                  <button
                                    type="button"
                                    className="cgpt-history-older-more"
                                    disabled={olderLoadingMore}
                                    onClick={() => void loadOlderChats({ append: true })}
                                  >
                                    {olderLoadingMore ? "Loading…" : "Load more"}
                                  </button>
                                ) : null}
                              </>
                            )
                          ) : null}
                        </div>
                      ) : null}
                    </>
                  )}
                </>
              )}
            </div>
          </>
        </div>
      </aside>

      <section className={`cgpt-main${activePrivateMode ? " cgpt-main--private" : ""}`}>
        {activePrivateMode ? <PrivateModeStrip /> : null}
        {readOnly && <ReadOnlyBanner className="readonly-account-banner--chat" />}
        <header className="cgpt-main-topbar">
          <UserProfile theme={theme} onThemeChange={setTheme} />
        </header>
        {chatError && <div className="cgpt-banner">{chatError}</div>}
        {modelsError && !chatError && <div className="cgpt-banner cgpt-banner-warn">{modelsError}</div>}

        <div className="cgpt-messages" ref={messagesScrollRef}>
          {messagesLoadingOlder ? (
            <div className="cgpt-banner cgpt-banner-warn">Loading older messages…</div>
          ) : null}
          {messages.length === 0 && (
            <div className="cgpt-welcome">
              <h2>{welcomeHeading}</h2>
            </div>
          )}
          {messages.map((m, i) => (
            <article
              key={`${activeId}-${i}`}
              className={`cgpt-msg cgpt-msg-${m.role}${m.modelId ? " cgpt-msg-multi" : ""}`}
            >
              {m.role === "assistant" && m.modelName ? (
                <div className="cgpt-msg-model-label" title={m.modelId}>
                  {shortModelName(m.modelName, m.modelId || "")}
                </div>
              ) : null}
              <div
                className="cgpt-msg-inner"
                dir={messageDirectionForContent(m.content)}
              >
                {(() => {
                  const attachPayload = readAttachmentMessage(m.content);
                  if (attachPayload) {
                    return <ChatAttachmentMessage payload={attachPayload} />;
                  }
                  const audioPayload = readAudioMessage(m.content);
                  if (audioPayload) {
                    return (
                      <ChatAudioMessage url={audioPayload.url} transcript={audioPayload.transcript} />
                    );
                  }
                  if (m.content === IMAGE_PENDING_MARKER) {
                    return (
                      <div className="cgpt-generated-block cgpt-generated-block--pending">
                        <div className="cgpt-generated-image cgpt-generated-image--loading">Generating image…</div>
                      </div>
                    );
                  }
                  const imagePayload = readImageMessage(m.content);
                  if (imagePayload) {
                    return (
                      <div className="cgpt-generated-block">
                        <AuthenticatedImage
                          url={imagePayload.url}
                          alt="Generated"
                          className="cgpt-generated-image"
                        />
                        <div className="cgpt-generated-actions">
                          <button type="button" onClick={() => void downloadImage(imagePayload.url)}>
                            Download
                          </button>
                          <button
                            type="button"
                            onClick={() => void openImageFullSize(imagePayload.url)}
                          >
                            Open full size
                          </button>
                          <button
                            type="button"
                            disabled={isSessionStreaming}
                            onClick={() => regenerateImage(i, imagePayload)}
                          >
                            Regenerate
                          </button>
                        </div>
                      </div>
                    );
                  }
                  const mdImage = extractMarkdownImage(m.content || "");
                  if (mdImage.imageUrl) {
                    return (
                      <div className="cgpt-generated-block">
                        <img
                          src={safeBrowserUrl(mdImage.imageUrl, "image") ?? ""}
                          alt="Generated"
                          className="cgpt-generated-image"
                        />
                        <div className="cgpt-generated-actions">
                          <button type="button" onClick={() => void downloadImage(mdImage.imageUrl || "")}>
                            Download
                          </button>
                          <button type="button" onClick={() => void openImageFullSize(mdImage.imageUrl || "")}>
                            Open full size
                          </button>
                        </div>
                        {mdImage.text ? (
                          <MarkdownContent content={mdImage.text} className="cgpt-markdown" />
                        ) : null}
                      </div>
                    );
                  }
                  const fallback = m.content || (isEmptyStreamingAssistant(i) && !activeTurnPhase ? "…" : "");
                  if (m.role === "assistant") {
                    const streamingThisMessage =
                      isSessionStreaming && i === messages.length - 1;
                    const showTurnStatus =
                      streamingThisMessage && !m.content?.trim() && activeTurnPhase;
                    return (
                      <>
                        {showTurnStatus ? (
                          <p className="cgpt-turn-status" aria-live="polite">
                            <span className="cgpt-turn-status__pulse" aria-hidden />
                            {turnPhaseLabel(activeTurnPhase)}
                          </p>
                        ) : null}
                        {m.content?.trim() || !showTurnStatus ? (
                          <MarkdownContent
                            content={fallback}
                            className={`cgpt-markdown${streamingThisMessage ? " cgpt-markdown--streaming" : ""}`}
                            streaming={streamingThisMessage}
                          />
                        ) : null}
                      </>
                    );
                  }
                  const plain = readAttachmentMessage(m.content) || readAudioMessage(m.content) ? "" : fallback;
                  return plain;
                })()}
              </div>
              <div className="cgpt-msg-actions">
                <MessageInfoButton title={chatMessageInfoTitle(m, m.role, messages, i)} />
                {m.role === "user" && (
                  <>
                    <button
                      type="button"
                      className="cgpt-msg-action-btn"
                      onClick={() => void retryUserPromptAt(i)}
                      title="Retry"
                      aria-label="Retry prompt"
                    >
                      ↻
                    </button>
                    <button
                      type="button"
                      className="cgpt-msg-action-btn"
                      onClick={() => void copyMessageContent(m.content, `${activeId}-${i}`)}
                    >
                      {copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy"}
                    </button>
                    <button
                      type="button"
                      className="cgpt-msg-action-btn"
                      onClick={() => editUserPrompt(m.content)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="cgpt-msg-action-btn"
                      onClick={() => deleteUserPromptAt(i)}
                    >
                      Delete
                    </button>
                  </>
                )}
                {m.role !== "user" && (
                  <>
                    {m.id &&
                    !activePrivateMode &&
                    m.content !== IMAGE_PENDING_MARKER &&
                    !m.streaming &&
                    !(isSessionStreaming && i === messages.length - 1) ? (
                      <>
                        <button
                          type="button"
                          className={`cgpt-msg-action-btn cgpt-msg-feedback-btn${m.feedback?.rating === 1 ? " is-active" : ""}`}
                          disabled={readOnly}
                          onClick={() => void rateAssistantMessage(i, 1)}
                          title="Helpful"
                          aria-label="Mark response as helpful"
                          aria-pressed={m.feedback?.rating === 1}
                        >
                          👍
                        </button>
                        <button
                          type="button"
                          className={`cgpt-msg-action-btn cgpt-msg-feedback-btn${m.feedback?.rating === -1 ? " is-active" : ""}`}
                          disabled={readOnly}
                          onClick={() => void rateAssistantMessage(i, -1)}
                          title="Not helpful"
                          aria-label="Mark response as not helpful"
                          aria-pressed={m.feedback?.rating === -1}
                        >
                          👎
                        </button>
                      </>
                    ) : null}
                    <button
                      type="button"
                      className="cgpt-msg-action-btn"
                      onClick={() => void copyMessageContent(m.content, `${activeId}-${i}`)}
                    >
                      {copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy"}
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
          <div ref={endRef} />
        </div>

        <footer className="cgpt-footer">
          {readOnly ? (
            <div className="cgpt-composer cgpt-composer--readonly card">
              <p className="muted-text" style={{ margin: 0 }}>
                Read-only mode — browse your chat history above. Sending messages and using models is disabled.
              </p>
            </div>
          ) : (
          <form className="cgpt-composer" onSubmit={send}>
            {showScrollToBottomBtn && messages.length > 0 ? (
              <button
                type="button"
                className="cgpt-scroll-to-bottom"
                onClick={jumpToChatBottom}
                aria-label="Scroll to latest messages"
                title="Jump to bottom"
              >
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
            ) : null}
            <div className="cgpt-composer-box">
              <input
                ref={fileInputRef}
                type="file"
                className="cgpt-file-input"
                accept={ATTACHMENT_ACCEPT}
                multiple
                onChange={(e) => void onAttachmentFilesSelected(e.target.files)}
                tabIndex={-1}
                aria-hidden
              />
              {pendingAttachments.length > 0 ? (
                <div className="cgpt-pending-attachments">
                  {pendingAttachments.map((a, idx) => (
                    <span key={`${a.url}-${idx}`} className="cgpt-pending-attachment">
                      <span className="cgpt-pending-attachment__name" title={a.name}>
                        {a.kind === "image" ? "🖼" : "📄"} {a.name}
                      </span>
                      <button
                        type="button"
                        className="cgpt-pending-attachment__remove"
                        onClick={() => removePendingAttachment(idx)}
                        aria-label={`Remove ${a.name}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              {activeQueue.length > 0 ? (
                <div className="cgpt-prompt-queue" aria-label="Queued messages">
                  {activeQueue.map((item, idx) => (
                    <div key={item.id} className="cgpt-prompt-queue__item">
                      <span className="cgpt-prompt-queue__index" aria-hidden>
                        {idx + 1}
                      </span>
                      <span className="cgpt-prompt-queue__text" title={queueItemPreview(item)}>
                        {queueItemPreview(item)}
                      </span>
                      <div className="cgpt-prompt-queue__actions">
                        <button
                          type="button"
                          className="cgpt-prompt-queue__btn"
                          onClick={() => editQueuedPrompt(item)}
                          aria-label="Edit queued message"
                          title="Edit"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          className="cgpt-prompt-queue__btn cgpt-prompt-queue__btn--remove"
                          onClick={() => activeId && removeQueuedPrompt(activeId, item.id)}
                          aria-label="Remove from queue"
                          title="Remove"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              <textarea
                ref={textareaRef}
                className={`cgpt-composer-input cgpt-composer-input--${inputDirection}${showWelcomeComposerPrompt ? " cgpt-composer-input--welcome-prompt" : ""}`}
                value={input}
                dir={inputDirection}
                onChange={onComposerInput}
                onSelect={onComposerSelect}
                onPaste={(e) => void onComposerPaste(e)}
                onKeyDown={onKeyDown}
                placeholder={composerPlaceholder}
                rows={1}
              />
              <div className="cgpt-composer-bar">
                <div className="cgpt-model-row">
                  <div className="cgpt-model-picker" ref={modelMenuRef}>
                    <button
                      type="button"
                      className="cgpt-composer-ctrl cgpt-model-trigger"
                      onClick={() => {
                        setToolsMenuOpen(false);
                        setModelMenuOpen((o) => !o);
                      }}
                      disabled={!models.length}
                      aria-expanded={modelMenuOpen}
                      aria-haspopup="listbox"
                    >
                      <span className="cgpt-composer-ctrl__icon" aria-hidden>
                        <ComposerModelIcon />
                      </span>
                      <span className="cgpt-composer-ctrl__label">
                        {currentModel
                          ? shortModelName(currentModel.name, currentModel.id)
                          : "Select model"}
                      </span>
                      <span className="cgpt-chevron" aria-hidden>
                        ▾
                      </span>
                    </button>
                    {modelMenuOpen && (
                      <div className="cgpt-model-menu" role="listbox">
                        <input
                          type="search"
                          className="cgpt-model-search"
                          placeholder="Search models…"
                          value={modelSearch}
                          onChange={(e) => setModelSearch(e.target.value)}
                          autoFocus
                        />
                        <ul>
                          {filteredModels.length === 0 && (
                            <li className="cgpt-model-empty">No models match</li>
                          )}
                          {filteredModels.map((m) => (
                            <li key={m.id} role="option" aria-selected={model === m.id}>
                              <button
                                type="button"
                                className={model === m.id ? "active" : ""}
                                onClick={() => pickModel(m.id)}
                                title={m.name}
                              >
                                {m.name}
                              </button>
                              <button
                                type="button"
                                className={`cgpt-model-default${defaultModel === m.id ? " is-default" : ""}`}
                                onClick={(e) => setAsDefaultModel(m.id, e)}
                                aria-label={
                                  defaultModel === m.id
                                    ? `${m.name} is default model`
                                    : `Set ${m.name} as default model`
                                }
                                title={defaultModel === m.id ? "Default model" : "Set as default for new chats"}
                              >
                                {defaultModel === m.id ? (
                                  <svg
                                    viewBox="0 0 24 24"
                                    width="15"
                                    height="15"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2.5"
                                    aria-hidden
                                  >
                                    <path
                                      d="M5 13l4 4L19 7"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                    />
                                  </svg>
                                ) : (
                                  <svg
                                    viewBox="0 0 24 24"
                                    width="15"
                                    height="15"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.8"
                                    opacity="0.45"
                                    aria-hidden
                                  >
                                    <circle cx="12" cy="12" r="9" />
                                  </svg>
                                )}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="cgpt-tools-picker" ref={toolsMenuRef}>
                    <button
                      ref={toolsTriggerRef}
                      type="button"
                      className="cgpt-composer-ctrl cgpt-model-trigger"
                      onClick={() => {
                        setModelMenuOpen(false);
                        setToolsMenuOpen((o) => !o);
                      }}
                      aria-expanded={toolsMenuOpen}
                      aria-haspopup="menu"
                      aria-label="Tools"
                    >
                      <span className="cgpt-composer-ctrl__icon" aria-hidden>
                        <ComposerToolsIcon />
                      </span>
                      <span className="cgpt-composer-ctrl__label">Tools</span>
                      {activeToolCount > 0 ? (
                        <span className="cgpt-composer-ctrl__badge">{activeToolCount}</span>
                      ) : null}
                      <span className="cgpt-chevron" aria-hidden>
                        ▾
                      </span>
                    </button>
                  <ServerToolsMenu
                    open={toolsMenuOpen}
                    anchorRef={toolsTriggerRef}
                    tools={chatTools}
                    privateMode={activePrivateMode}
                    onChange={updateChatTools}
                    onPrivateModeChange={togglePrivateMode}
                    onClose={() => setToolsMenuOpen(false)}
                  />
                  </div>
                  <button
                    type="button"
                    className={`cgpt-composer-ctrl cgpt-translate-eng-btn${translateToEngBusy ? " is-busy" : ""}`}
                    onClick={() => void handleTranslateToEng()}
                    disabled={
                      !input.trim() ||
                      translateToEngBusy ||
                      !textNeedsEnglishTranslation(input) ||
                      !model
                    }
                    aria-busy={translateToEngBusy}
                    aria-label={translateToEngBusy ? "Translating to English" : "Translate to English"}
                    title={
                      translateToEngBusy
                        ? "Translating…"
                        : textNeedsEnglishTranslation(input)
                          ? "Translate composer text to English"
                          : "Already in English"
                    }
                  >
                    {translateToEngBusy ? (
                      <span className="cgpt-composer-ctrl__spinner" aria-hidden />
                    ) : (
                      <span className="cgpt-composer-ctrl__icon" aria-hidden>
                        <ComposerTranslateIcon />
                      </span>
                    )}
                    <span className="cgpt-composer-ctrl__label">To ENG</span>
                  </button>
                </div>
                <div className="cgpt-send-group">
                  {isStopVisible ? (
                    <button
                      type="button"
                      className="cgpt-stop"
                      onClick={() => stopGenerating(activeId)}
                      aria-label="Stop generating"
                      title="Stop generating"
                    >
                      ■
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="cgpt-attach-btn"
                    onClick={openAttachmentPicker}
                    disabled={attachUploading || !model}
                    aria-label="Attach file"
                    title="Attach file"
                  >
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.64 16.2a2 2 0 0 1-2.83-2.83l8.49-8.49" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className={voiceRecording ? "cgpt-stop cgpt-voice-btn--recording" : "cgpt-voice-btn"}
                    onClick={() => void toggleVoiceRecording()}
                    disabled={voiceBusy || !model}
                    aria-label={voiceRecording ? "Stop recording" : "Record voice message"}
                    title={voiceRecording ? "Stop and insert text" : "Record voice → text in box"}
                  >
                    {voiceRecording ? (
                      "■"
                    ) : (
                      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden>
                        <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V19H9v2h6v-2h-2v-1.08A7 7 0 0 0 19 11h-2z" />
                      </svg>
                    )}
                  </button>
                  <button
                    type="submit"
                    className="cgpt-send"
                    disabled={
                      (!input.trim() && !pendingAttachments.length) ||
                      !model ||
                      voiceBusy ||
                      attachUploading
                    }
                    aria-label={isSessionStreaming ? "Queue message" : "Send message"}
                    title={isSessionStreaming ? "Add to queue" : "Send message"}
                  >
                    ↑
                  </button>
                </div>
              </div>
            </div>
          </form>
          )}
          <p className="cgpt-disclaimer">Alpha Router can make mistakes. Check important info.</p>
        </footer>
      </section>

      <ColorPickerModal
        open={!!colorPickerFolderId}
        title="Folder color"
        value={folders.find((f) => f.id === colorPickerFolderId)?.color ?? null}
        onClose={() => setColorPickerFolderId(null)}
        onChange={(color) => {
          if (colorPickerFolderId) setFolderColor(colorPickerFolderId, color);
        }}
      />

    </div>
  );
}
