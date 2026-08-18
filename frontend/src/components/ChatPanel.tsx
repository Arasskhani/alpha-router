import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api, authFetch, formatApiError, getCachedSession, isApiAuthError } from "../api";
import { chatModelsEmptyMessage, normalizeChatModelsError } from "../lib/chatMessages";
import AuthenticatedImage from "./AuthenticatedImage";
import AuthenticatedVideo from "./AuthenticatedVideo";
import AuthenticatedAudio from "./AuthenticatedAudio";
import MarkdownContent from "./MarkdownContent";
import ModelName from "./ModelName";
import ModelProviderIcon from "./ModelProviderIcon";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { useReadOnly } from "../context/ReadOnlyContext";
import { useShellMenu } from "../context/ShellMenuContext";
import { useChatModelChromeRegister } from "../context/ChatModelChromeContext";
import { useConfirm } from "../context/ConfirmContext";
import RowActionsMenu from "./RowActionsMenu";
import ColorPickerModal from "./ColorPickerModal";
import MoveToFolderModal from "./MoveToFolderModal";
import { IconFolder } from "./icons/navIcons";
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
  mergeSessionAfterMessageLoad,
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
import {
  CHAT_REFRESH_EVENT_NAME,
  isChatLeader,
  onChatLeaderChange,
} from "../lib/chatLeader";
import { formatLocalDateTimeFromMs } from "../lib/dateTime";
import { BROWSER_EVENT_NAMES, PRODUCT_NAME, STORAGE_KEYS } from "../lib/brand";
import {
  notifyReplyReady,
  REPLY_READY_FOCUS_EVENT,
} from "../lib/replyReadyNotify";
import { getSessionUser, isSessionActive, logout } from "../lib/session";
import { copyFreshChatTools, toolsToApiPayload, type ChatToolsState } from "../lib/chatTools";
import ChatAttachmentMessage from "./chat/ChatAttachmentMessage";
import ChatAudioMessage from "./chat/ChatAudioMessage";
import ServerToolsMenu from "./chat/ServerToolsMenu";
import ChatModelPickerModal from "./chat/ChatModelPickerModal";
import {
  ComposerAgentIcon,
  ComposerToolsIcon,
  ComposerTranslateIcon,
} from "./chat/ComposerControlIcons";
import {
  MAX_MULTI_MODELS,
  shortcutModKey,
} from "../lib/chatModelPresets";
import {
  DownloadIcon,
  OpenFullSizeIcon,
  RegenerateIcon,
  CsvIcon,
  PdfIcon,
  DocIcon,
  TxtIcon,
} from "./chat/GeneratedImageIcons";
import RequestLogCostDetailsModal from "./RequestLogCostDetailsModal";
import {
  fetchOwnedRequestLog,
  fetchOwnedRequestLogCostDetails,
  type CostDetails,
  type RequestLogSummary,
} from "../lib/requestLogCostDetails";
import VirtualSidebarList from "./chat/ChatSidebarVirtual";
import PrivateModeLockIcon from "./chat/PrivateModeLockIcon";
import { BrowserSpeechCapture, pickVoiceRecordingMime } from "../lib/voiceInput";
import {
  ATTACHMENT_ACCEPT,
  AUDIO_MESSAGE_PREFIX,
  attachmentDisplayText,
  attachmentMessage,
  buildApiMessageContent,
  buildApiMessageContentAsync,
  type ApiContentPart,
  cloneProcessedAttachments,
  compactChatMessagesForStorage,
  hasApiContent,
  DEFAULT_MAX_ATTACHMENTS,
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
  IMAGE_MESSAGE_PREFIX,
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
  isBackgroundVideoRunning,
  parseVideoMessage,
  runBackgroundVideoGeneration,
  shouldRouteToVideoGeneration,
  stopBackgroundVideoGeneration,
  subscribeBackgroundVideoUpdates,
  VIDEO_MESSAGE_PREFIX,
  VIDEO_PENDING_MARKER,
  type VideoPayload,
} from "../lib/chatVideo";
import {
  findVideoGenerationFallbackModel,
  modelSupportsVideos,
  resolveVideoGenerationModel as resolveConcreteVideoModel,
  resolveSessionModelForVideoTools,
} from "../lib/chatVideoModels";
import {
  buildStoppedSpeechMessages,
  isBackgroundSpeechRunning,
  parseSpeechMessage,
  runBackgroundSpeechGeneration,
  shouldRouteToSpeechGeneration,
  SPEECH_MESSAGE_PREFIX,
  SPEECH_PENDING_MARKER,
  stopBackgroundSpeechGeneration,
  subscribeBackgroundSpeechUpdates,
  type SpeechPayload,
} from "../lib/chatSpeech";
import {
  findSpeechGenerationFallbackModel,
  modelSupportsSpeech,
  resolveSpeechGenerationModel as resolveConcreteSpeechModel,
  resolveSessionModelForSpeechTools,
  resolveSpeechVoiceForModel,
} from "../lib/chatSpeechModels";
import {
  codeInterpreterBlockedReason,
  findCodeInterpreterFallbackModel,
  modelSupportsCodeInterpreter,
  type CodeInterpreterCompatibility,
} from "../lib/chatCodeInterpreterModels";
import {
  findTextChatFallbackModel,
  isAutoRouterModel,
  modelSupportsTextChat,
  resolveDefaultModelPreference,
  resolvePromptAssistModel,
} from "../lib/chatModels";
import { applyPersianFontToChat, normalizePersianFontId } from "../lib/persianFonts";
import { copyTextToClipboard } from "../lib/clipboard";
import { downloadCsv, downloadTxt, exportMessagePdf, exportMessageDocx } from "../lib/chatExport";
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
import {
  NO_AGENT_SELECTION,
  agentCompletionMetadataFromSse,
  agentRequestFields,
  decideAgentHandoff,
  fetchAgentCatalog,
  fetchPendingAgentHandoffs,
  formatAgentAnswerForDisplay,
  nextAgentSelection,
  resolveAgentSelection,
  type AgentCatalogItem,
  type AgentCompletionMetadata,
  type AgentHandoff,
} from "../lib/agentChat";
import {
  AgentCitationList,
  AgentHandoffBanner,
} from "./chat/AgentExperience";
import AgentMenu from "./chat/AgentMenu";

type Model = {
  id: string;
  name: string;
  external_id?: string;
  is_system_default?: boolean;
  kinds?: string[];
  is_image_model?: boolean;
  supports_text_to_image?: boolean;
  supports_image_to_image?: boolean;
  is_video_model?: boolean;
  supports_text_to_video?: boolean;
  supports_image_to_video?: boolean;
  supported_durations?: number[];
  supported_resolutions?: string[];
  supported_aspect_ratios?: string[];
  is_speech_model?: boolean;
  supports_text_to_speech?: boolean;
  supported_voices?: string[];
  supported_formats?: string[];
  supported_speeds?: [number, number] | number[];
  max_text_length?: number;
  supports_vision?: boolean;
  code_interpreter?: CodeInterpreterCompatibility | null;
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
      return "Searching the web";
    case "writing":
      return "Writing";
    case "preparing":
    default:
      return "Preparing";
  }
}

/** Three LTR dots that fade in/out in sequence while the turn is pending. */
function TurnStatusDots() {
  return (
    <span className="alpha-router-turn-status__dots" aria-hidden>
      <span className="alpha-router-turn-status__dot">.</span>
      <span className="alpha-router-turn-status__dot">.</span>
      <span className="alpha-router-turn-status__dot">.</span>
    </span>
  );
}
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
  const video = readVideoMessage(content);
  if (video?.prompt?.trim()) return video.prompt.trim();
  const speech = readSpeechMessage(content);
  if (speech?.prompt?.trim()) return speech.prompt.trim();
  return content;
}

function messageDirectionForContent(content: string): TextDirection {
  if (
    content === IMAGE_PENDING_MARKER ||
    content.startsWith(IMAGE_MESSAGE_PREFIX) ||
    content === VIDEO_PENDING_MARKER ||
    content.startsWith(VIDEO_MESSAGE_PREFIX) ||
    content === SPEECH_PENDING_MARKER ||
    content.startsWith(SPEECH_MESSAGE_PREFIX)
  ) {
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

function readVideoMessage(content: string): VideoPayload | null {
  return parseVideoMessage(content);
}

function readSpeechMessage(content: string): SpeechPayload | null {
  return parseSpeechMessage(content);
}

/** Last assistant slot is a speech placeholder still being generated. */
function messagesHavePendingSpeech(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === SPEECH_PENDING_MARKER;
}

/** Last assistant slot is a video placeholder still being generated. */
function messagesHavePendingVideo(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === VIDEO_PENDING_MARKER;
}

function buildStoppedVideoMessages(
  messages: ChatMessage[],
  stoppedText = "Video generation stopped.",
): ChatMessage[] {
  const withoutPending = messages.filter((m) => m.content !== VIDEO_PENDING_MARKER);
  const last = withoutPending.at(-1);
  if (last?.role === "assistant" && last.content === stoppedText) return withoutPending;
  return [
    ...withoutPending,
    { role: "assistant", content: stoppedText, receivedAt: Date.now() },
  ];
}

function readImageMessage(content: string): ImagePayload | null {
  if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    try {
      return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
    } catch {
      return null;
    }
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

/** CSV / Word / PDF actions only for real text replies (not image/audio/pending). */
function isTextAssistantExportable(content: string): boolean {
  if (!content?.trim()) return false;
  if (content === IMAGE_PENDING_MARKER) return false;
  if (content === VIDEO_PENDING_MARKER) return false;
  if (content === SPEECH_PENDING_MARKER) return false;
  if (readImageMessage(content)) return false;
  if (readVideoMessage(content)) return false;
  if (readSpeechMessage(content)) return false;
  if (readAudioMessage(content)) return false;
  const md = extractMarkdownImage(content);
  if (md.imageUrl && !md.text.trim()) return false;
  return true;
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

function MessageInfoButton({
  title,
  onClick,
}: {
  title: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className="alpha-router-msg-action-btn alpha-router-msg-action-btn--info"
      title={title}
      aria-label={title}
      onClick={onClick}
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
    <div className="alpha-router-private-strip" role="status">
      <PrivateModeLockIcon className="alpha-router-private-strip__icon" size={18} />
      <p className="alpha-router-private-strip__text">
        <span className="alpha-router-private-strip__title">Private Mode is ON</span>
        <span className="alpha-router-private-strip__sep" aria-hidden>
          {" "}
          :{" "}
        </span>
        <span className="alpha-router-private-strip__body">
          Private Mode is permanent for this chat. Messages and media are stored only in this browser and
          will be <strong className="alpha-router-private-strip__danger">deleted</strong> when you log out or clear
          browser data.
        </span>
      </p>
    </div>
  );
}

type ParsedChatApiError = {
  message: string;
  code?: string;
  retryAfterSeconds?: number;
};

class ChatCompletionApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly retryAfterSeconds?: number;

  constructor(parsed: ParsedChatApiError, status: number) {
    super(parsed.message);
    this.name = "ChatCompletionApiError";
    this.status = status;
    this.code = parsed.code;
    this.retryAfterSeconds = parsed.retryAfterSeconds;
  }
}

export default function ChatPanel() {
  const readOnly = useReadOnly();
  const shellMenu = useShellMenu();
  const registerModelChrome = useChatModelChromeRegister();
  const { confirm } = useConfirm();
  const [models, setModels] = useState<Model[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [model, setModel] = useState("");
  const [agentCatalog, setAgentCatalog] = useState<AgentCatalogItem[]>([]);
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  const [pendingHandoffs, setPendingHandoffs] = useState<AgentHandoff[]>([]);
  const [handoffBusyId, setHandoffBusyId] = useState<string | null>(null);
  /** Multi-model selection; send fans out to each id in order (primary = first). */
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const selectedModelIdsRef = useRef<string[]>([]);
  selectedModelIdsRef.current = selectedModelIds;
  const [modelPickerMode, setModelPickerMode] = useState<"replace" | "append" | null>(null);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const sessionUser = getSessionUser();
  const sessionUsername = sessionUser?.username ?? "";
  const welcomeName = sessionUser?.display_name || sessionUsername;
  const modKey = useMemo(() => shortcutModKey(), []);
  const [chatTools, setChatTools] = useState<ChatToolsState>(() => copyFreshChatTools());
  const chatToolsRef = useRef(chatTools);
  chatToolsRef.current = chatTools;
  const [translateToEngBusy, setTranslateToEngBusy] = useState(false);
  const [defaultModel, setDefaultModel] = useState("");
  const [voiceRecordingLang, setVoiceRecordingLang] = useState("en");
  const [persianFont, setPersianFont] = useState("");
  /** False until user prefs hydrate (or fail) so we never stamp a catalog fallback before the saved default arrives. */
  const [userPrefsReady, setUserPrefsReady] = useState(false);
  const serverDefaultModelRef = useRef<string | null | undefined>(undefined);
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
  const [movingSessionIds, setMovingSessionIds] = useState<string[] | null>(null);
  const [selectedChatIds, setSelectedChatIds] = useState<Set<string>>(() => new Set());
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
  const [costDetailsLog, setCostDetailsLog] = useState<RequestLogSummary | null>(null);
  const [costDetails, setCostDetails] = useState<CostDetails | null>(null);
  const [costDetailsLoading, setCostDetailsLoading] = useState(false);
  const [costDetailsError, setCostDetailsError] = useState("");
  const [draggingSessionId, setDraggingSessionId] = useState<string | null>(null);
  const [dropFolderId, setDropFolderId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  const pinScrollToBottomRef = useRef(true);
  const [showScrollToBottomBtn, setShowScrollToBottomBtn] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const toolsMenuRef = useRef<HTMLDivElement>(null);
  const toolsTriggerRef = useRef<HTMLButtonElement>(null);
  const agentMenuRef = useRef<HTMLDivElement>(null);
  const agentTriggerRef = useRef<HTMLButtonElement>(null);
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
  const [maxAttachments, setMaxAttachments] = useState(DEFAULT_MAX_ATTACHMENTS);
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
  const replyNotifyPrefsRef = useRef({ away: false, sound: true });

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
      isBackgroundVideoRunning(activeId) ||
      isBackgroundSpeechRunning(activeId) ||
      sessionHasPendingImage(messages) ||
      messagesHavePendingVideo(messages) ||
      messagesHavePendingSpeech(messages));
  const activeTurnPhase = activeId ? turnPhases[activeId] : undefined;
  const activeQueue = activeId ? promptQueues[activeId] || [] : [];
  const returningChatUser = isReturningChatUser(sessions);
  const welcomeHeading = getChatWelcomeHeading({
    name: welcomeName,
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

  const pickerModels = useMemo((): Model[] => {
    const matched = models.filter((m) => {
      if (chatTools.imageGeneration && !modelSupportsImages(m, models)) return false;
      if (chatTools.videoGeneration && !modelSupportsVideos(m, models)) return false;
      if (chatTools.speechGeneration && !modelSupportsSpeech(m, models)) return false;
      if (chatTools.codeInterpreter && !modelSupportsCodeInterpreter(m)) return false;
      // Plain text chat: hide embeddings/rerank/media-only models that cannot answer chat.
      if (
        !chatTools.imageGeneration &&
        !chatTools.videoGeneration &&
        !chatTools.speechGeneration &&
        !modelSupportsTextChat(m)
      ) {
        return false;
      }
      return true;
    });
    const autoRouter = matched.find((m) => isAutoRouterModel(m));
    if (!autoRouter) return matched;
    return [autoRouter, ...matched.filter((m) => m.id !== autoRouter.id)];
  }, [
    models,
    chatTools.imageGeneration,
    chatTools.videoGeneration,
    chatTools.speechGeneration,
    chatTools.codeInterpreter,
  ]);

  const selectedModels = useMemo(
    () =>
      selectedModelIds
        .map((id) => models.find((m) => m.id === id))
        .filter((m): m is Model => !!m),
    [selectedModelIds, models],
  );

  const activeSession = activeId ? sessions.find((s) => s.id === activeId) : null;
  const activePrivateMode = isPrivateChat(activeSession);
  const activeSessionAgent = activeSession?.currentAgentId
    ? agentCatalog.find((agent) => agent.id === activeSession.currentAgentId)
    : undefined;
  const activeAgentSelection = activeId
    ? resolveAgentSelection(activeSession?.selectedAgentSlug, activeSessionAgent?.slug)
    : NO_AGENT_SELECTION;
  const agentModeActive = activeAgentSelection !== NO_AGENT_SELECTION;
  const activeAgentName =
    agentCatalog.find((agent) => agent.slug === activeAgentSelection)?.name || "";

  const activeToolCount = useMemo(() => {
    let n = 0;
    if (chatTools.webSearch) n += 1;
    if (chatTools.webFetch) n += 1;
    if (chatTools.imageGeneration) n += 1;
    if (chatTools.videoGeneration) n += 1;
    if (chatTools.speechGeneration) n += 1;
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

  function agentSelectionForSession(sessionId: string): string {
    const session = sessionsRef.current.find((item) => item.id === sessionId);
    const bound = session?.currentAgentId
      ? agentCatalog.find((agent) => agent.id === session.currentAgentId)
      : undefined;
    return resolveAgentSelection(session?.selectedAgentSlug, bound?.slug);
  }

  /** Agents are mutually exclusive per chat; picking the active one turns it off. */
  function toggleAgentForActiveSession(slug: string) {
    const sessionId = activeIdRef.current || ensureActiveSession();
    if (!sessionId) return;
    const selection = nextAgentSelection(agentSelectionForSession(sessionId), slug);
    const cleared = selection === NO_AGENT_SELECTION;
    persistSessions(
      (prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                selectedAgentSlug: cleared ? null : selection,
                // Drop the sticky binding so handoff polling and the next turn
                // both follow the user's choice to run without an Agent.
                ...(cleared
                  ? { currentAgentId: null, currentAgentVersionId: null }
                  : {}),
              }
            : s,
        ),
      { debounce: false },
    );
    if (!cleared) {
      const primary = selectedModelIdsRef.current[0] || model;
      if (primary) setSelectedModelIds([primary]);
    }
  }

  function applyAgentMetadataToSession(
    sessionId: string,
    metadata?: AgentCompletionMetadata,
  ) {
    if (!metadata?.agentId) return;
    const selected = agentCatalog.find((agent) => agent.id === metadata.agentId);
    const next = sessionsRef.current.map((session) =>
      session.id === sessionId
        ? {
            ...session,
            currentAgentId: metadata.agentId,
            currentAgentVersionId: metadata.agentVersionId ?? session.currentAgentVersionId,
            selectedAgentSlug: selected?.slug ?? session.selectedAgentSlug,
            agentSelectedAt: Date.now(),
          }
        : session,
    );
    sessionsRef.current = next;
    setSessions(next);
  }

  async function handleAgentHandoff(
    handoff: AgentHandoff,
    decision: "accept" | "decline",
  ) {
    setHandoffBusyId(handoff.id);
    setChatError("");
    try {
      const result = await decideAgentHandoff(handoff.id, decision);
      setPendingHandoffs((prev) => prev.filter((item) => item.id !== handoff.id));
      if (
        decision === "accept"
        && activeIdRef.current
        && result.agent_id
        && result.agent_slug
      ) {
        const sessionId = activeIdRef.current;
        const next = sessionsRef.current.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                currentAgentId: result.agent_id,
                selectedAgentSlug: result.agent_slug,
                agentSelectedAt: Date.now(),
              }
            : session,
        );
        sessionsRef.current = next;
        setSessions(next);
      }
    } catch (error) {
      reportUserFacingApiError(error);
    } finally {
      setHandoffBusyId(null);
    }
  }

  /** Speech > video > image when multiple legacy flags survive a session payload. */
  function resolveModelForTools(sessionModel: string | undefined, tools: ChatToolsState): string {
    const fallback = (current?: string) => resolveNewChatModel(models, current, defaultModel);
    if (tools.speechGeneration) {
      return resolveSessionModelForSpeechTools(models, sessionModel, true, fallback);
    }
    if (tools.videoGeneration) {
      return resolveSessionModelForVideoTools(models, sessionModel, true, fallback);
    }
    return resolveSessionModelForTools(models, sessionModel, tools.imageGeneration, fallback);
  }

  function resolveModelForSession(session: ChatSession): string {
    return resolveModelForTools(session.model, sessionTools(session));
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
    return (
      !!abortControllersRef.current[sessionId] ||
      isBackgroundImageRunning(sessionId) ||
      isBackgroundVideoRunning(sessionId) ||
      isBackgroundSpeechRunning(sessionId)
    );
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
    if (sessionId && isBackgroundVideoRunning(sessionId)) return;
    if (sessionId && isBackgroundSpeechRunning(sessionId)) return;
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
      // Resolve against the live ref first. React may defer the setState updater,
      // and title/metadata push reads sessionsRef / the chatSessionsProvider.
      const resolved =
        typeof next === "function" ? next(sessionsRef.current) : next;
      sessionsRef.current = resolved;
      const metaIds = opts?.metadataSessionIds;
      if (metaIds?.length) {
        for (const id of metaIds) {
          const row = resolved.find((s) => s.id === id);
          if (row && !row.privateMode) markSessionMetadataDirty(id);
        }
      }
      scheduleServerChatSave({ debounce: opts?.debounce !== false });
      setSessions(resolved);
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
      if (!sessionPrivateMode(sid)) {
        void pushSessionMetadataToServer(sid).catch(() => {});
      }
    },
    [persistSessions],
  );

  const applyLoadedSessionMessages = useCallback(
    (sessionId: string, loaded: ChatSession) => {
      const live = sessionsRef.current.find((s) => s.id === sessionId);
      const merged = mergeSessionAfterMessageLoad(live, loaded);
      const next = sessionsRef.current.map((s) => (s.id === sessionId ? merged : s));
      sessionsRef.current = next;
      setSessions(next);
      patchDefaultTitleFromMessages(sessionId, merged.messages);
    },
    [patchDefaultTitleFromMessages],
  );

  const updateSessionMessages = useCallback((sessionId: string, msgs: ChatMessage[]) => {
    if (sessionId === activeIdRef.current) {
      messagesRef.current = msgs;
      setMessages(msgs);
    }
    const idx = sessionsRef.current.findIndex((s) => s.id === sessionId);
    if (idx < 0) {
      // New chat may not be in sessionsRef yet; keep messagesRef and retry on next write.
      return;
    }
    const next = sessionsRef.current.map((s, i) =>
      i === idx ? withSessionMessagesActivity(s, msgs) : s,
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
        if (isBackgroundImageRunning(sid) || isBackgroundVideoRunning(sid) || isBackgroundSpeechRunning(sid)) {
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
      setUserPrefsReady(true);
      return;
    }
    let cancelled = false;
    api<{ max_chat_attachments_count?: number }>("/api/chat/attachment-limits")
      .then((limits) => {
        if (cancelled) return;
        const count = Number(limits?.max_chat_attachments_count);
        if (Number.isFinite(count) && count >= 1) {
          setMaxAttachments(Math.min(50, Math.round(count)));
        }
      })
      .catch(() => {
        /* keep DEFAULT_MAX_ATTACHMENTS */
      });
    api<Model[]>("/api/chat/models", { cache: "no-store" })
      .then((m) => {
        if (cancelled) return;
        setModels(m);
        setModelsError(m.length ? "" : chatModelsEmptyMessage());
        if (!m.length) return;
        // Prefer the active session's stored model over the global default (stale
        // closure on model must not overwrite a per-chat selection after hydrate).
        const sid = activeIdRef.current;
        const sessionModel = (
          sid ? sessionsRef.current.find((s) => s.id === sid)?.model : ""
        )?.trim() || "";
        setModel((prev) => {
          const prevTrim = (prev || "").trim();
          if (prevTrim && m.some((row) => row.id === prevTrim || row.external_id === prevTrim)) {
            const match = m.find((row) => row.id === prevTrim || row.external_id === prevTrim);
            return match?.id || prevTrim;
          }
          if (sessionModel) {
            const match = m.find(
              (row) => row.id === sessionModel || row.external_id === sessionModel,
            );
            return match?.id || sessionModel;
          }
          if (!userPrefsReady) return prev;
          return resolveNewChatModel(m, prevTrim || undefined, defaultModel);
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setModels([]);
        setModelsError(normalizeChatModelsError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [readOnly, defaultModel, userPrefsReady]);

  useEffect(() => {
    if (readOnly || !sessionUsername) {
      setAgentCatalog([]);
      return;
    }
    let cancelled = false;
    void fetchAgentCatalog()
      .then((catalog) => {
        if (cancelled) return;
        setAgentCatalog(Array.isArray(catalog.items) ? catalog.items : []);
      })
      .catch(() => {
        if (cancelled) return;
        setAgentCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, [readOnly, sessionUsername]);

  useEffect(() => {
    if (
      readOnly
      || !activeId
      || activePrivateMode
      || (
        activeAgentSelection === NO_AGENT_SELECTION
        && !activeSession?.currentAgentId
      )
    ) {
      setPendingHandoffs([]);
      return;
    }
    const sessionId = activeId;
    let cancelled = false;
    const load = () => {
      void fetchPendingAgentHandoffs(sessionId)
        .then((items) => {
          if (!cancelled && activeIdRef.current === sessionId) {
            setPendingHandoffs(items);
          }
        })
        .catch(() => {
          // A new chat may not exist on the server until its first turn.
        });
    };
    load();
    const timer = window.setInterval(load, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    activeAgentSelection,
    activeId,
    activePrivateMode,
    activeSession?.currentAgentId,
    readOnly,
  ]);

  useEffect(() => {
    if (!models.length || !activeId || !chatsHydrated) return;
    const session = sessionsRef.current.find((s) => s.id === activeId);
    if (!session) return;
    const stored = (session.model || "").trim();
    // Per-chat model wins. Default is only for sessions that never chose a model.
    const resolved = resolveModelForTools(session.model, sessionTools(session));
    if (!resolved) return;
    setModel((prev) => (prev === resolved ? prev : resolved));
    // Persist only remaps (e.g. external_id → catalog id, image-tool swap) — never
    // replace a stored per-chat model with the user default after refresh.
    if (stored && stored !== resolved) {
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
    } else if (!stored && userPrefsReady && resolved) {
      // Brand-new session with empty model: stamp the resolved choice once.
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
  }, [userPrefsReady, models, activeId, chatsHydrated, defaultModel, persistSessions]);

  useEffect(() => {
    if (readOnly || !sessionUsername) {
      setUserPrefsReady(true);
      return;
    }
    serverDefaultModelRef.current = undefined;
    setUserPrefsReady(false);
    let cancelled = false;
    void hydrateUserPrefsFromServer()
      .then((prefs) => {
        if (cancelled) return;
        serverDefaultModelRef.current = prefs.default_model;
        setDefaultModel(prefs.default_model || "");
        setVoiceRecordingLang(prefs.voice_recording_language === "fa" ? "fa" : "en");
        setPersianFont(normalizePersianFontId(prefs.persian_font));
        replyNotifyPrefsRef.current = {
          away: !!prefs.reply_notify_away,
          sound: prefs.reply_notify_sound !== false,
        };
        setUserPrefsReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        serverDefaultModelRef.current = null;
        setDefaultModel("");
        setVoiceRecordingLang("en");
        setPersianFont("");
        replyNotifyPrefsRef.current = { away: false, sound: true };
        setUserPrefsReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [readOnly, sessionUsername]);

  useEffect(() => {
    function onPrefsSaved() {
      void hydrateUserPrefsFromServer()
        .then((prefs) => {
          setVoiceRecordingLang(prefs.voice_recording_language === "fa" ? "fa" : "en");
          setPersianFont(normalizePersianFontId(prefs.persian_font));
          replyNotifyPrefsRef.current = {
            away: !!prefs.reply_notify_away,
            sound: prefs.reply_notify_sound !== false,
          };
          if (prefs.default_model != null) {
            setDefaultModel(prefs.default_model || "");
            serverDefaultModelRef.current = prefs.default_model;
          }
        })
        .catch(() => {});
    }
    window.addEventListener(BROWSER_EVENT_NAMES.userPrefsSaved, onPrefsSaved);
    return () => window.removeEventListener(BROWSER_EVENT_NAMES.userPrefsSaved, onPrefsSaved);
  }, []);

  useEffect(() => {
    async function onChatsImported() {
      if (!chatsHydratedRef.current) return;
      try {
        const remote = await fetchUserChatsFromServer({ limit: 200 });
        const protectedIds = new Set<string>([
          ...Object.keys(streamingSessionsRef.current),
          ...getBackgroundImageSessionIds(),
        ]);
        const merged = mergeRemoteChatSessions(sessionsRef.current, remote.sessions, protectedIds);
        sessionsRef.current = merged;
        commitServerListSync(merged);
        setSessions(merged);
        setFolders((prev) => {
          const byId = new Map(prev.map((f) => [f.id, f]));
          for (const f of remote.folders) byId.set(f.id, f);
          return [...byId.values()].sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
        });
        setSessionsTotal(remote.total ?? merged.length);
        if (remote.older_total != null) setOlderTotal(remote.older_total);
        setHydrateOutcome(merged.length > 0 ? "ok" : "empty");
      } catch {
        /* keep current sidebar */
      }
    }
    window.addEventListener(BROWSER_EVENT_NAMES.chatsImported, onChatsImported);
    return () => window.removeEventListener(BROWSER_EVENT_NAMES.chatsImported, onChatsImported);
  }, []);

  useEffect(() => {
    applyPersianFontToChat(persianFont);
  }, [persianFont]);

  useEffect(() => {
    if (!userPrefsReady || !models.length || !defaultModel) return;
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
  }, [userPrefsReady, models, defaultModel]);

  useEffect(() => {
    if (!models.length || !model) return;
    if (models.some((m) => m.id === model)) return;
    const byExternal = models.find((m) => m.external_id === model);
    if (byExternal) {
      setModel(byExternal.id);
      return;
    }
    // Prefer the active session's stored model over the global default.
    const sid = activeIdRef.current;
    const sessionModel = (
      sid ? sessionsRef.current.find((s) => s.id === sid)?.model : ""
    )?.trim() || "";
    if (sessionModel) {
      const match = models.find(
        (m) => m.id === sessionModel || m.external_id === sessionModel,
      );
      if (match) {
        setModel(match.id);
        return;
      }
      // Keep the per-chat id even if temporarily missing from catalog.
      if (sessionModel === model) return;
      setModel(sessionModel);
      return;
    }
    if (!userPrefsReady) return;
    // No per-chat model — heal UI from default / catalog only.
    setModel(resolveNewChatModel(models, undefined, defaultModel));
  }, [userPrefsReady, models, model, defaultModel]);

  useEffect(() => {
    if (
      !models.length ||
      !model ||
      chatTools.imageGeneration ||
      chatTools.videoGeneration ||
      chatTools.speechGeneration
    ) {
      return;
    }
    const current = models.find((m) => m.id === model || m.external_id === model);
    if (!current || modelSupportsTextChat(current)) return;
    const fallback = findTextChatFallbackModel(models);
    if (!fallback || fallback.id === current.id) return;
    setModel(fallback.id);
    setSelectedModelIds((prev) => (prev.length <= 1 ? [fallback.id] : prev));
    const sid = activeIdRef.current || ensureActiveSession();
    if (sid) {
      persistSessions(
        (prev) => prev.map((s) => (s.id === sid ? { ...s, model: fallback.id } : s)),
        { debounce: false, metadataSessionIds: [sid] },
      );
      if (!sessionPrivateMode(sid)) {
        void pushSessionMetadataToServer(sid).catch(() => {});
      }
    }
    setChatError(
      `${current.name} is not available for text chat. Switched to ${fallback.name}.`,
    );
  }, [
    models,
    model,
    chatTools.imageGeneration,
    chatTools.videoGeneration,
    chatTools.speechGeneration,
  ]);

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
              applyLoadedSessionMessages(first.id, loaded);
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
    window.addEventListener(CHAT_REFRESH_EVENT_NAME, onRefresh);
    return () => {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      window.removeEventListener(CHAT_REFRESH_EVENT_NAME, onRefresh);
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
    const onBackgroundMediaUpdate = (sessionId: string) => {
      if (isBackgroundImageRunning(sessionId) || isBackgroundVideoRunning(sessionId) || isBackgroundSpeechRunning(sessionId)) {
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
    };
    const unsubscribeImage = subscribeBackgroundImageUpdates(onBackgroundMediaUpdate);
    const unsubscribeVideo = subscribeBackgroundVideoUpdates(onBackgroundMediaUpdate);
    const unsubscribeSpeech = subscribeBackgroundSpeechUpdates(onBackgroundMediaUpdate);
    return () => {
      unsubscribeImage();
      unsubscribeVideo();
      unsubscribeSpeech();
    };
  }, [syncSessionsFromServer, persistSessions]);

  useEffect(() => {
    const hasNonPrivatePending = sessions.some(
      (s) =>
        (sessionHasPendingImage(s.messages) ||
          messagesHavePendingVideo(s.messages) ||
          messagesHavePendingSpeech(s.messages)) &&
        !s.privateMode,
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
      if (
        streamingSessionsRef.current[sid] &&
        !isBackgroundImageRunning(sid) &&
        !isBackgroundVideoRunning(sid) &&
        !isBackgroundSpeechRunning(sid)
      ) {
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
    if (!userPrefsReady || !models.length) return;
    const m = resolveNewChatModel(models, undefined, defaultModel);
    if (!m) return;
    const freshTools = copyFreshChatTools();
    const s = createSession(m, "New chat", freshTools);
    persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
    activeIdRef.current = s.id;
    setActiveId(s.id);
    setModel(s.model);
    setMessages([]);
    setChatTools(freshTools);
  }, [
    hydrateOutcome,
    chatsHydrated,
    activeId,
    readOnly,
    userPrefsReady,
    models,
    defaultModel,
    persistSessions,
  ]);

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
        applyLoadedSessionMessages(activeId, loaded);
      });
    } else {
      setMessages(s.messages);
      setMessagesHasOlder(false);
    }
  }, [activeId, sessions, scrollChatToBottom, applyLoadedSessionMessages, syncScrollPinFromContainer]);

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
    if (!toolsMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (toolsMenuRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest(".alpha-router-server-tools-menu")) return;
      setToolsMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [toolsMenuOpen]);

  useEffect(() => {
    if (!agentMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (agentMenuRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest(".alpha-router-agent-menu")) return;
      setAgentMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [agentMenuOpen]);

  useEffect(() => {
    setAgentMenuOpen(false);
  }, [activeId]);

  // Reset pills when switching chats. Same-session multi-select is owned by
  // replace/append/remove helpers (Search replaces; Add Model appends).
  const selectionSessionRef = useRef<string | null>(null);
  useEffect(() => {
    if (selectionSessionRef.current === activeId) return;
    selectionSessionRef.current = activeId;
    setSelectedModelIds(model ? [model] : []);
  }, [activeId, model]);

  // If primary model is healed/changed without going through the picker, keep
  // it in the selection (as first) without dropping other selected models.
  useEffect(() => {
    if (!activeId || selectionSessionRef.current !== activeId) return;
    if (!model) {
      setSelectedModelIds([]);
      return;
    }
    setSelectedModelIds((prev) => {
      if (prev.length === 0) return [model];
      if (prev[0] === model) return prev;
      if (prev.includes(model)) return [model, ...prev.filter((id) => id !== model)];
      return [model];
    });
  }, [model, activeId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        setToolsMenuOpen(false);
        setModelPickerMode("replace");
      } else if (e.key.toLowerCase() === "j") {
        e.preventDefault();
        setToolsMenuOpen(false);
        setModelPickerMode("append");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    registerModelChrome({
      openReplacePicker: () => {
        setToolsMenuOpen(false);
        setModelPickerMode("replace");
      },
      modelsReady: models.length > 0,
      modKey,
    });
    return () => registerModelChrome(null);
  }, [registerModelChrome, models.length, modKey]);

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
      userMessage?: ChatMessage;
      assistantClientMessageId: string;
      /** Default true. False = append assistant only (later models in a multi-model turn). */
      includeUserMessage?: boolean;
    },
    privateMode = false,
  ) {
    const toolsPayload = toolsToApiPayload(tools);
    const includeUser = persist?.includeUserMessage !== false && persist?.userMessage;
    const sessionId = persist?.sessionId || activeIdRef.current;
    const agentFields =
      !privateMode && sessionId
        ? agentRequestFields(agentSelectionForSession(sessionId))
        : {};
    return {
      model: modelId,
      messages: await apiMessages(history, forModel, privateMode),
      stream: true,
      private_mode: !!privateMode,
      ...toolsPayload,
      ...agentFields,
      ...(persist
        ? {
            chat_session_id: persist.sessionId,
            persist_chat: true,
            ...(includeUser && persist.userMessage
              ? {
                  user_message: {
                    role: persist.userMessage.role,
                    content: persist.userMessage.content,
                    clientMessageId: persist.userMessage.clientMessageId,
                    sentAt: persist.userMessage.sentAt,
                  },
                }
              : {}),
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
    // flushSync so sessionsRef includes the new chat before the first send turn.
    flushSync(() => {
      persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
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
        applyLoadedSessionMessages(id, loaded);
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

  useEffect(() => {
    function onReplyReadyFocus(ev: Event) {
      const detail = (ev as CustomEvent<{ sessionId?: string }>).detail;
      const sid = typeof detail?.sessionId === "string" ? detail.sessionId.trim() : "";
      if (!sid) return;
      activateSessionFromRef(sid);
    }
    window.addEventListener(REPLY_READY_FOCUS_EVENT, onReplyReadyFocus as EventListener);
    return () => window.removeEventListener(REPLY_READY_FOCUS_EVENT, onReplyReadyFocus as EventListener);
  }, []);

  function isSuccessfulNotifyContent(content: string): boolean {
    const text = (content || "").trim();
    if (!text) return false;
    if (
      text === IMAGE_PENDING_MARKER ||
      text === VIDEO_PENDING_MARKER ||
      text === SPEECH_PENDING_MARKER
    ) {
      return false;
    }
    if (text.startsWith("Error:") || text.startsWith("No response from model.")) return false;
    if (
      text === "Image generation stopped." ||
      text === "Speech generation stopped." ||
      text.startsWith("Image generation timed out") ||
      text.startsWith("Speech generation timed out") ||
      text.startsWith("Preparing the")
    ) {
      return false;
    }
    return true;
  }

  function maybeNotifyReplyReady(sessionId: string, messageKey: string, content: string) {
    if (readOnly) return;
    if (!replyNotifyPrefsRef.current.away) return;
    if (!isSuccessfulNotifyContent(content)) return;
    const session = sessionsRef.current.find((s) => s.id === sessionId);
    notifyReplyReady({
      sessionId,
      activeId: activeIdRef.current,
      title: session?.title || "Chat",
      sound: replyNotifyPrefsRef.current.sound,
      messageKey,
    });
  }

  /** After image/video/speech jobs that may finish without throwing on abort. */
  function maybeNotifyMediaReady(sessionId: string, messageKey?: string, allowRetry = true) {
    const fromActive =
      sessionId === activeIdRef.current ? messagesRef.current : undefined;
    const fromSession = sessionsRef.current.find((s) => s.id === sessionId)?.messages;
    const msgs = fromActive?.length ? fromActive : fromSession?.length ? fromSession : getSessionMessages(sessionId);
    let lastAssistant: ChatMessage | undefined;
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      if (msgs[i].role === "assistant") {
        lastAssistant = msgs[i];
        break;
      }
    }
    if (!lastAssistant) return;
    const content = lastAssistant.content || "";
    const stillPending =
      content === IMAGE_PENDING_MARKER ||
      content === VIDEO_PENDING_MARKER ||
      content === SPEECH_PENDING_MARKER;
    if (stillPending) {
      // Image/speech sync may land in sessionsRef a tick after the job resolves.
      if (allowRetry) {
        window.setTimeout(() => maybeNotifyMediaReady(sessionId, messageKey, false), 400);
      }
      return;
    }
    const mediaOk =
      content.startsWith(IMAGE_MESSAGE_PREFIX) ||
      content.startsWith(VIDEO_MESSAGE_PREFIX) ||
      content.startsWith(SPEECH_MESSAGE_PREFIX);
    if (!mediaOk) return;
    const key =
      (messageKey || "").trim() ||
      lastAssistant.clientMessageId ||
      lastAssistant.id ||
      `${sessionId}:media:${lastAssistant.receivedAt ?? Date.now()}`;
    maybeNotifyReplyReady(sessionId, key, content);
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
    flushSync(() => {
      persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
      activeIdRef.current = s.id;
      pinScrollToBottomRef.current = true;
      setActiveId(s.id);
      setModel(m);
      setMessages([]);
      setChatTools(freshTools);
    });
    clearChatSelection();
    setToolsMenuOpen(false);
    setChatError("");
    requestAnimationFrame(() => scrollChatToBottom("auto"));
  }

  async function removeChatSession(id: string): Promise<void> {
    stopBackgroundImageGeneration(id);
    stopBackgroundVideoGeneration(id);
    clearComposerDraft(id);
    setSelectedChatIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
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

  async function deleteSession(id: string, e?: React.MouseEvent) {
    e?.stopPropagation();
    if (readOnly) return;
    await removeChatSession(id);
  }

  function startRenameSession(session: ChatSession, e?: React.MouseEvent) {
    e?.stopPropagation();
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
    persistSessions(
      (prev) =>
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
      { debounce: false, metadataSessionIds: [sid] },
    );
    if (!sessionPrivateMode(sid)) {
      void pushSessionMetadataToServer(sid).catch(() => {});
    }
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
    const affectedIds = sessionsRef.current
      .filter((s) => s.folderId === folderId)
      .map((s) => s.id);
    removeFolderRecord(folderId);
    persistSessions(
      (prev) => prev.map((s) => (s.folderId === folderId ? { ...s, folderId: null } : s)),
      { debounce: false, metadataSessionIds: affectedIds },
    );
    for (const id of affectedIds) {
      if (!sessionPrivateMode(id)) {
        void pushSessionMetadataToServer(id).catch(() => {});
      }
    }
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
    persistSessions(
      (prev) => prev.map((s) => (s.id === sessionId ? { ...s, folderId } : s)),
      { debounce: false, metadataSessionIds: [sessionId] },
    );
    if (!sessionPrivateMode(sessionId)) {
      void pushSessionMetadataToServer(sessionId).catch(() => {});
    }
    setDropFolderId(null);
  }

  function moveSessionsToFolder(sessionIds: string[], folderId: string | null) {
    if (!sessionIds.length) return;
    const idSet = new Set(sessionIds);
    persistSessions(
      (prev) => prev.map((s) => (idSet.has(s.id) ? { ...s, folderId } : s)),
      { debounce: false, metadataSessionIds: sessionIds },
    );
    for (const sessionId of sessionIds) {
      if (!sessionPrivateMode(sessionId)) {
        void pushSessionMetadataToServer(sessionId).catch(() => {});
      }
    }
    setDropFolderId(null);
    setSelectedChatIds(new Set());
  }

  function toggleChatSelected(sessionId: string) {
    setSelectedChatIds((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  }

  function clearChatSelection() {
    setSelectedChatIds(new Set());
  }

  function selectAllVisibleChats() {
    setSelectedChatIds(new Set(filteredSessions.map((s) => s.id)));
  }

  async function deleteSelectedChats() {
    if (readOnly) return;
    const ids = [...selectedChatIds];
    if (!ids.length) return;
    const ok = await confirm({
      title: "Delete chats",
      message: `Delete ${ids.length} chat${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    const active = activeIdRef.current;
    const ordered =
      active && ids.includes(active) ? [...ids.filter((id) => id !== active), active] : ids;
    clearChatSelection();
    for (const id of ordered) {
      await removeChatSession(id);
    }
  }

  function sessionDisplayTitle(s: ChatSession): string {
    if (!isDefaultChatTitle(s.title)) return s.title;
    const derived = sessionTitleFromMessages(s.messages);
    return !isDefaultChatTitle(derived) ? derived : s.title || DEFAULT_CHAT_TITLE;
  }

  function renderSessionRow(s: ChatSession, wrap: "li" | "div" = "li") {
    const isRenaming = renamingSessionId === s.id;
    const isSelected = selectedChatIds.has(s.id);
    const selectionActive = selectedChatIds.size > 0;
    const inner = (
      <>
        {!readOnly && !isRenaming ? (
          <label
            className={`alpha-router-history-check${isSelected || selectionActive ? " is-visible" : ""}`}
            title="Select chat"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => toggleChatSelected(s.id)}
              aria-label={`Select ${sessionDisplayTitle(s)}`}
            />
          </label>
        ) : null}
        {isRenaming ? (
          <form
            className="alpha-router-history-rename"
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
            className={`alpha-router-history-item${s.id === activeId ? " active" : ""}${isSelected ? " is-selected" : ""}${streamingSessions[s.id] || isBackgroundImageRunning(s.id) || isBackgroundVideoRunning(s.id) || isBackgroundSpeechRunning(s.id) ? " is-streaming" : ""}`}
            onClick={() => selectSession(s.id)}
          >
            {s.privateMode ? (
              <span className="alpha-router-history-item__lock" title="Private Mode" aria-hidden>
                <PrivateModeLockIcon className="alpha-router-history-item__lock-icon" size={14} />
              </span>
            ) : null}
            {streamingSessions[s.id] || isBackgroundImageRunning(s.id) || isBackgroundVideoRunning(s.id) || isBackgroundSpeechRunning(s.id) ? (
              <span className="alpha-router-history-item__busy" title="Generating…" aria-hidden />
            ) : null}
            {sessionDisplayTitle(s)}
          </button>
        )}
        {!readOnly && !isRenaming ? (
          <div
            className="alpha-router-history-item-actions"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="alpha-router-history-delete"
              title="Delete chat"
              aria-label={`Delete ${sessionDisplayTitle(s)}`}
              onClick={(e) => void deleteSession(s.id, e)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
              </svg>
            </button>
            <RowActionsMenu
              label="⋯"
              menuClassName="row-actions-menu--sidebar"
              actions={[
                { label: "Rename", onClick: () => startRenameSession(s) },
                { label: "Move", onClick: () => setMovingSessionIds([s.id]) },
                {
                  label: "Delete",
                  onClick: () => void deleteSession(s.id),
                  danger: true,
                },
              ]}
            />
          </div>
        ) : null}
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
    const rowClass = `alpha-router-history-row${isSelected ? " is-selected" : ""}`;
    if (wrap === "div") {
      return (
        <div key={s.id} className={rowClass} {...dragProps}>
          {inner}
        </div>
      );
    }
    return (
      <li key={s.id} className={isSelected ? "is-selected" : undefined} {...dragProps}>
        {inner}
      </li>
    );
  }

  function persistSessionPrimaryModel(id: string) {
    setChatError("");
    const sid = activeIdRef.current || ensureActiveSession();
    if (!sid) return;
    persistSessions(
      (prev) => prev.map((s) => (s.id === sid ? { ...s, model: id } : s)),
      { debounce: false, metadataSessionIds: [sid] },
    );
    if (!sessionPrivateMode(sid)) {
      void pushSessionMetadataToServer(sid).catch(() => {});
    }
  }

  /** Search modal: replace entire multi-selection with one model. */
  function replaceModelSelection(id: string) {
    setModel(id);
    setSelectedModelIds([id]);
    setModelPickerMode(null);
    persistSessionPrimaryModel(id);
  }

  /** Add Model: append for multi-model UI (blocked while media generation is on). */
  function appendModelSelection(id: string) {
    if (
      chatToolsRef.current.imageGeneration ||
      chatToolsRef.current.videoGeneration ||
      chatToolsRef.current.speechGeneration
    ) {
      // Media generation is single-model only — Add Model replaces the primary.
      replaceModelSelection(id);
      return;
    }
    setSelectedModelIds((prev) => {
      if (prev.includes(id)) return prev;
      if (prev.length >= MAX_MULTI_MODELS) return prev;
      const next = prev.length === 0 ? [id] : [...prev, id];
      if (prev.length === 0) {
        setModel(id);
        persistSessionPrimaryModel(id);
      }
      return next;
    });
    setModelPickerMode(null);
  }

  function removeSelectedModel(id: string) {
    setSelectedModelIds((prev) => {
      const next = prev.filter((x) => x !== id);
      if (id === model) {
        const primary = next[0] || "";
        setModel(primary);
        if (primary) persistSessionPrimaryModel(primary);
      }
      return next;
    });
  }

  function pickModel(id: string) {
    replaceModelSelection(id);
  }

  function resolveImageGenerationModel(candidate: Model): Model {
    if (isAutoRouterModel(candidate)) return candidate;
    // Resolve for the request only — do not collapse multi-selection via pickModel.
    return resolveConcreteImageModel(models, candidate);
  }

  function resolveVideoGenerationModel(candidate: Model): Model {
    if (isAutoRouterModel(candidate)) return candidate;
    // Resolve for the request only — do not collapse multi-selection via pickModel.
    return resolveConcreteVideoModel(models, candidate);
  }

  function resolveSpeechGenerationModel(candidate: Model): Model {
    if (isAutoRouterModel(candidate)) return candidate;
    return resolveConcreteSpeechModel(models, candidate);
  }

  function willRoutePromptToVideoGeneration(tools: ChatToolsState, primaryModel: Model): boolean {
    if (!tools.videoGeneration) return false;
    const turnModel = resolveVideoGenerationModel(primaryModel);
    return shouldRouteToVideoGeneration({
      videoGenerationEnabled: true,
      modelSupportsVideo: modelSupportsVideos(turnModel, models),
    });
  }

  function willRoutePromptToSpeechGeneration(tools: ChatToolsState, primaryModel: Model): boolean {
    if (!tools.speechGeneration) return false;
    const turnModel = resolveSpeechGenerationModel(primaryModel);
    return shouldRouteToSpeechGeneration({
      speechGenerationEnabled: true,
      modelSupportsSpeech: modelSupportsSpeech(turnModel, models),
    });
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

  function setAsDefaultModel(id: string, e?: { stopPropagation(): void; preventDefault(): void }) {
    e?.stopPropagation();
    e?.preventDefault();
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
      userMessage?: ChatMessage;
      assistantClientMessageId: string;
      includeUserMessage?: boolean;
    },
    privateMode = false,
  ): Promise<{
    content: string;
    requestLogId?: number;
    agentMetadata?: AgentCompletionMetadata;
  }> {
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
    if (!res.ok) {
      const parsed = parseApiError(await res.text(), res.status);
      const retryAfterHeader = Number(res.headers.get("Retry-After"));
      if (
        parsed.retryAfterSeconds == null
        && Number.isFinite(retryAfterHeader)
        && retryAfterHeader > 0
      ) {
        parsed.retryAfterSeconds = Math.ceil(retryAfterHeader);
      }
      throw new ChatCompletionApiError(parsed, res.status);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response stream");

    const decoder = new TextDecoder();
    let assistant = "";
    let buffer = "";
    let requestLogId: number | undefined;
    let agentMetadata: AgentCompletionMetadata | undefined;

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
          const metaLogId = json?.alpha_router?.request_log_id;
          if (typeof metaLogId === "number" && Number.isFinite(metaLogId)) {
            requestLogId = metaLogId;
          }
          const nextAgentMetadata = agentCompletionMetadataFromSse(
            json?.alpha_router,
          );
          if (Object.keys(nextAgentMetadata).length) {
            agentMetadata = {
              ...(agentMetadata || {}),
              ...nextAgentMetadata,
            };
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
    return {
      content: assistant,
      ...(requestLogId != null ? { requestLogId } : {}),
      ...(agentMetadata ? { agentMetadata } : {}),
    };
  }

  async function openMessageCostDetails(requestLogId: number) {
    setCostDetailsLog({
      id: requestLogId,
      request_time: "",
      username: "",
      model_id: "",
      prompt_language: "",
      prompt_tokens: 0,
      completion_tokens: 0,
      total_cost_usd: 0,
      response_time_ms: 0,
      source_ip: "",
      success: true,
    });
    setCostDetails(null);
    setCostDetailsError("");
    setCostDetailsLoading(true);
    try {
      const [log, details] = await Promise.all([
        fetchOwnedRequestLog(requestLogId),
        fetchOwnedRequestLogCostDetails(requestLogId),
      ]);
      setCostDetailsLog(log);
      setCostDetails(details);
    } catch (err) {
      setCostDetailsError(err instanceof Error ? err.message : "Failed to load cost details");
    } finally {
      setCostDetailsLoading(false);
    }
  }

  function closeMessageCostDetails() {
    setCostDetailsLog(null);
    setCostDetails(null);
    setCostDetailsError("");
    setCostDetailsLoading(false);
  }

  type TextTurnPersistCtx = {
    userMessage: ChatMessage;
    assistantClientMessageId: string;
    /** When false, server appends only the assistant row (multi-model siblings). */
    includeUserMessage?: boolean;
  };

  type RunChatTurnOptions = {
    skipTitle?: boolean;
    skipReconcile?: boolean;
    /** When false, never route this turn to /api/images or /api/videos (multi-model text siblings). */
    allowImageRoute?: boolean;
  };

  function historyForCompletionApi(history: ChatMessage[]): ChatMessage[] {
    const last = history.at(-1);
    if (last?.role === "assistant" && !(last.content || "").trim()) {
      return history.slice(0, -1);
    }
    return history;
  }

  /** API history for a multi-model turn: through the user message only (no sibling assistants). */
  function historyThroughUserMessage(
    messages: ChatMessage[],
    userMessage: ChatMessage,
  ): ChatMessage[] {
    let uidx = -1;
    if (userMessage.clientMessageId) {
      uidx = messages.findIndex((m) => m.clientMessageId === userMessage.clientMessageId);
    }
    if (uidx < 0 && userMessage.sentAt != null) {
      uidx = messages.findIndex((m) => m.role === "user" && m.sentAt === userMessage.sentAt);
    }
    if (uidx < 0) {
      for (let i = messages.length - 1; i >= 0; i -= 1) {
        if (messages[i]?.role === "user") {
          uidx = i;
          break;
        }
      }
    }
    if (uidx < 0) return historyForModelRequest(historyForCompletionApi(messages));
    return historyForModelRequest(messages.slice(0, uidx + 1));
  }

  function resolveTurnModels(primary: Model): Model[] {
    const ids = selectedModelIdsRef.current.length
      ? selectedModelIdsRef.current
      : [primary.id];
    const out: Model[] = [];
    const seen = new Set<string>();
    for (const id of ids) {
      const m =
        models.find((x) => x.id === id) || models.find((x) => x.external_id === id);
      if (!m || seen.has(m.id)) continue;
      seen.add(m.id);
      out.push(m);
      if (out.length >= MAX_MULTI_MODELS) break;
    }
    return out.length ? out : [primary];
  }

  function isDedicatedMediaModel(m?: Model | null): boolean {
    if (!m || isAutoRouterModel(m)) return false;
    if (m.is_video_model || m.supports_text_to_video) return true;
    if (m.is_speech_model || m.supports_text_to_speech) return true;
    // Pure image generators often cannot run chat_title completions.
    if ((m.is_image_model || m.supports_text_to_image) && !m.supports_vision) return true;
    return false;
  }

  function resolveSessionTitleModelId(mediaModelId?: string): string {
    const preferred =
      resolveDefaultModelPreference(models, defaultModel) ||
      resolveDefaultModelPreference(
        models,
        models.find((m) => m.is_system_default)?.id,
      );
    if (preferred) {
      const preferredModel = models.find((m) => m.id === preferred);
      if (preferredModel && !isDedicatedMediaModel(preferredModel)) return preferred;
    }
    const auto = models.find(isAutoRouterModel);
    if (auto) return auto.id;
    const textModel = models.find((m) => !isDedicatedMediaModel(m));
    if (textModel) return textModel.id;
    return (mediaModelId || "").trim();
  }

  function friendlyTurnError(err: unknown): string {
    if (
      err instanceof ChatCompletionApiError
      && err.code === "code_interpreter_capacity_busy"
    ) {
      const retry =
        err.retryAfterSeconds && err.retryAfterSeconds > 0
          ? ` Try again in about ${err.retryAfterSeconds} seconds.`
          : " Please try again later.";
      return `Code Interpreter is currently busy.${retry}`;
    }
    if (
      err instanceof ChatCompletionApiError
      && err.code === "code_interpreter_capacity_unavailable"
    ) {
      return "Code Interpreter is temporarily unavailable because capacity coordination is offline. Please try again shortly.";
    }
    if (
      err instanceof ChatCompletionApiError
      && err.code === "code_interpreter_workspace_limit"
    ) {
      return err.message;
    }
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes("network") || message === "Failed to fetch") {
      return `Cannot reach ${PRODUCT_NAME} API. Check that Docker is running and hard-refresh (Ctrl+Shift+R).`;
    }
    return message;
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
    options?: RunChatTurnOptions,
  ) {
    const emptyReply =
      "No response from model. Check Connections and enable the model in Admin → Models.";
    const turnSession = sessionsRef.current.find((s) => s.id === sid);
    const specialistTurn =
      !sessionPrivateMode(sid)
      && agentSelectionForSession(sid) !== NO_AGENT_SELECTION;
    const turnTools = specialistTurn
      ? copyFreshChatTools()
      : sid === activeIdRef.current
        ? chatToolsRef.current
        : sessionTools(turnSession);

    const historyForApi = historyForCompletionApi(historyWithUser);
    const scopedHistory = historyForModelRequest(historyForApi);

    const userContent =
      scopedHistory.filter((m) => m.role === "user").at(-1)?.content || "";
    const promptText = promptTextFromUserContent(userContent);
    const allowMediaRoute = options?.allowImageRoute !== false;

    // Speech wins over video/image/text when its tool is on for this turn.
    if (allowMediaRoute && willRoutePromptToSpeechGeneration(turnTools, primaryModel)) {
      const speechModel = resolveSpeechGenerationModel(primaryModel);
      const titleModelId = resolveSessionTitleModelId(speechModel.id);
      const speechVoice = resolveSpeechVoiceForModel(speechModel, turnTools.speechVoice);
      if (speechVoice !== turnTools.speechVoice) {
        updateChatTools({ ...turnTools, speechVoice });
      }
      const speechAssistantId = newClientMessageId();
      const pendingMsgs: ChatMessage[] = [
        ...historyForApi,
        {
          role: "assistant",
          content: SPEECH_PENDING_MARKER,
          clientMessageId: speechAssistantId,
        },
      ];
      flushSync(() => updateSessionMessages(sid, pendingMsgs));
      const privateMode = sessionPrivateMode(sid);
      try {
        await syncSessionMessagesToServer(sid, pendingMsgs);
        await runBackgroundSpeechGeneration({
          sessionId: sid,
          localMessages: historyForApi,
          text: promptText,
          modelId: speechModel.id,
          privateMode,
          voice: speechVoice,
          format: turnTools.speechFormat,
          speed: turnTools.speechSpeed,
          assistantClientMessageId: speechAssistantId,
        });
        setChatError("");
        deferSessionTitle(sid, titleModelId, getSessionMessages(sid));
        maybeNotifyMediaReady(sid, speechAssistantId);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setChatError(friendlyTurnError(err));
        void scheduleSessionTitle(sid, titleModelId, getSessionMessages(sid));
      }
      return;
    }

    // Video wins over both image and text when its tool is on for this turn.
    if (allowMediaRoute && willRoutePromptToVideoGeneration(turnTools, primaryModel)) {
      const videoModel = resolveVideoGenerationModel(primaryModel);
      const titleModelId = resolveSessionTitleModelId(videoModel.id);
      const videoAssistantId = newClientMessageId();
      const pendingMsgs: ChatMessage[] = [
        ...historyForApi,
        {
          role: "assistant",
          content: VIDEO_PENDING_MARKER,
          clientMessageId: videoAssistantId,
        },
      ];
      flushSync(() => updateSessionMessages(sid, pendingMsgs));
      const privateMode = sessionPrivateMode(sid);
      try {
        // Ensure the durable worker can replace the pending marker in SQL.
        // Without this barrier a fast completion can leave the video only in
        // Media Library, while the prompt disappears after refresh.
        await syncSessionMessagesToServer(sid, pendingMsgs);
        await runBackgroundVideoGeneration({
          sessionId: sid,
          prompt: promptText,
          model: videoModel.id,
          userContent,
          history: scopedHistory.slice(0, -1),
          persist: !privateMode,
          duration: turnTools.videoDuration,
          resolution: turnTools.videoResolution,
          aspectRatio: turnTools.videoAspectRatio,
          generateAudio: turnTools.videoGenerateAudio,
          assistantClientMessageId: videoAssistantId,
          onUpdate: (msgs) => updateSessionMessages(sid, msgs),
          getMessages: () => getSessionMessages(sid),
        });
        setChatError("");
        deferSessionTitle(sid, titleModelId, getSessionMessages(sid));
        maybeNotifyMediaReady(sid, videoAssistantId);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setChatError(friendlyTurnError(err));
        void scheduleSessionTitle(sid, titleModelId, getSessionMessages(sid));
      }
      return;
    }

    const usePriorImage = promptImpliesImageEdit(promptText);
    const priorImage = usePriorImage
      ? lastAssistantImageUrl(scopedHistory.slice(0, -1))
      : undefined;
    const referenceImage = await resolveImageGenerationReferenceAsync(
      userContent,
      scopedHistory.slice(0, -1),
      usePriorImage,
    );
    const allowImageRoute = allowMediaRoute;
    const turnModel =
      allowImageRoute && turnTools.imageGeneration
        ? resolveImageGenerationModel(primaryModel)
        : primaryModel;

    if (
      allowImageRoute &&
      shouldRouteToImageGeneration(
        userContent,
        turnTools.imageGeneration,
        modelSupportsTextToImage(turnModel, models),
        modelSupportsImageToImage(turnModel, models),
        priorImage,
      )
    ) {
      if (referenceImage && !modelSupportsImageToImage(turnModel, models)) {
        const errAssistant: ChatMessage = {
          role: "assistant",
          content:
            "Error: The selected model does not support image-to-image. Choose a model that accepts image input (e.g. Gemini image or FLUX Kontext).",
          receivedAt: Date.now(),
          clientMessageId: newClientMessageId(),
          modelId: turnModel.id,
          modelName: turnModel.name,
        };
        const base =
          historyForApi.at(-1)?.role === "assistant" && !(historyForApi.at(-1)?.content || "").trim()
            ? historyForApi.slice(0, -1)
            : historyForApi;
        const errMsgs: ChatMessage[] = [...base, errAssistant];
        const userForPersist =
          persistCtx?.userMessage ?? base.filter((m) => m.role === "user").at(-1) ?? undefined;
        flushSync(() => applyMessages(sid, errMsgs));
        if (!sessionPrivateMode(sid)) {
          void finalizeAssistantOnServer(sid, errAssistant.content, {
            receivedAt: errAssistant.receivedAt,
            modelId: turnModel.id,
            modelName: turnModel.name,
            clientMessageId: errAssistant.clientMessageId,
            userMessage: userForPersist,
          }).catch((err) => reportSyncError(err, sid));
        }
        return;
      }
      const imageAssistantId = newClientMessageId();
      const pendingMsgs: ChatMessage[] = [
        ...historyForApi,
        {
          role: "assistant",
          content: IMAGE_PENDING_MARKER,
          clientMessageId: imageAssistantId,
        },
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
          assistantClientMessageId: imageAssistantId,
        });
        setChatError("");
        maybeNotifyMediaReady(sid, imageAssistantId);
        const titleModelId = resolveSessionTitleModelId(turnModel.id);
        if (sessionPrivateMode(sid)) {
          const local = sessionsRef.current.find((s) => s.id === sid);
          if (local) {
            deferSessionTitle(sid, titleModelId, local.messages);
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
            deferSessionTitle(sid, titleModelId, msgs);
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setChatError(friendlyTurnError(err));
        const titleModelId = resolveSessionTitleModelId(turnModel.id);
        if (sessionPrivateMode(sid)) {
          const local = sessionsRef.current.find((s) => s.id === sid);
          if (local) {
            void scheduleSessionTitle(sid, titleModelId, local.messages);
          }
        } else {
          const session = await fetchSessionWithMessages(sid);
          if (session) {
            const local = getLocalMessagesForSession(sid);
            const msgs = mergeChatMessagesPreferLocal(
              local.length ? local : sessionsRef.current.find((s) => s.id === sid)?.messages ?? [],
              session.messages,
            );
            flushSync(() => updateSessionMessages(sid, msgs));
            void scheduleSessionTitle(sid, titleModelId, msgs);
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
    const includeUserMessage = persistCtx?.includeUserMessage !== false;

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

    const liveForApi = getSessionMessages(sid);
    const apiHistory = historyThroughUserMessage(
      liveForApi.length ? liveForApi : historyWithUser,
      userMsg,
    );

    const patchAssistantInSession = (
      content: string,
      receivedAt?: number,
      requestLogId?: number,
      agentMetadata?: AgentCompletionMetadata,
    ) => {
      const current = getSessionMessages(sid);
      const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content,
        clientMessageId: assistantClientMessageId,
        modelId: primaryModel.id,
        modelName: primaryModel.name,
        ...(receivedAt != null ? { receivedAt } : {}),
        ...(requestLogId != null ? { requestLogId } : {}),
        ...(agentMetadata || {}),
      };
      if (idx >= 0) {
        const next = [...current];
        next[idx] = { ...current[idx], ...assistantMsg };
        return next;
      }
      return [...apiHistory, assistantMsg];
    };

    const useServerPersist = !sessionPrivateMode(sid);
    const streamed = await streamTextCompletion(
      primaryModel.id,
      apiHistory,
      primaryModel,
      controller.signal,
      (content) => {
        if (turnPhasesRef.current[sid] !== "writing") {
          setTurnPhase(sid, "writing");
        }
        applyMessagesStreaming(sid, patchAssistantInSession(content));
      },
      turnTools,
      useServerPersist
        ? {
            sessionId: sid,
            userMessage: userMsg,
            assistantClientMessageId,
            includeUserMessage,
          }
        : undefined,
      sessionPrivateMode(sid),
    );
    const receivedAt = Date.now();
    const finalContent = streamed.content.trim() ? streamed.content : emptyReply;
    const finalMsgs = patchAssistantInSession(
      finalContent,
      receivedAt,
      streamed.requestLogId,
      streamed.agentMetadata,
    );
    applyMessages(sid, finalMsgs);
    applyAgentMetadataToSession(sid, streamed.agentMetadata);
    maybeNotifyReplyReady(sid, assistantClientMessageId, finalContent);
    if (useServerPersist && !options?.skipReconcile) {
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
    if (streamed.agentMetadata?.agentRunId) {
      void fetchPendingAgentHandoffs(sid)
        .then((items) => {
          if (activeIdRef.current === sid) setPendingHandoffs(items);
        })
        .catch(() => {});
    }
    patchDefaultTitleFromMessages(sid, finalMsgs);
    if (!options?.skipTitle) {
      void scheduleSessionTitle(sid, primaryModel.id, finalMsgs);
    }
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
        if (fallback) {
          pickModel(fallback.id);
          return;
        }
      }
      // Image generation is single-model — collapse any multi-selection to primary.
      const primary = current?.id || model;
      if (primary) {
        setSelectedModelIds((prev) => (prev.length <= 1 ? prev : [primary]));
      }
    }
    if (next.videoGeneration) {
      const current = models.find((m) => m.id === model);
      if (!current || !modelSupportsVideos(current, models)) {
        const fallback = findVideoGenerationFallbackModel(models);
        if (fallback) {
          pickModel(fallback.id);
          return;
        }
        setChatError("No video-capable model is available. Enable one in Admin → Models.");
      }
      // Video generation is single-model — collapse any multi-selection to primary.
      const primary = current?.id || model;
      if (primary) {
        setSelectedModelIds((prev) => (prev.length <= 1 ? prev : [primary]));
      }
    }
    if (next.speechGeneration) {
      const current = models.find((m) => m.id === model);
      if (!current || !modelSupportsSpeech(current, models)) {
        const fallback = findSpeechGenerationFallbackModel(models);
        if (fallback) {
          const remappedVoice = resolveSpeechVoiceForModel(fallback, next.speechVoice);
          if (remappedVoice !== next.speechVoice) {
            const withVoice = { ...next, speechVoice: remappedVoice };
            setChatTools(withVoice);
            if (sid) {
              persistSessions(
                (prev) =>
                  prev.map((s) =>
                    s.id === sid
                      ? { ...s, tools: { ...withVoice }, toolsTouched: true, updatedAt: Date.now() }
                      : s,
                  ),
                { debounce: false, metadataSessionIds: [sid] },
              );
            }
          }
          pickModel(fallback.id);
          return;
        }
        setChatError("No speech-capable model is available. Enable one in Admin → Models.");
      } else {
        const remappedVoice = resolveSpeechVoiceForModel(current, next.speechVoice);
        if (remappedVoice !== next.speechVoice) {
          const withVoice = { ...next, speechVoice: remappedVoice };
          setChatTools(withVoice);
          if (sid) {
            persistSessions(
              (prev) =>
                prev.map((s) =>
                  s.id === sid
                    ? { ...s, tools: { ...withVoice }, toolsTouched: true, updatedAt: Date.now() }
                    : s,
                ),
              { debounce: false, metadataSessionIds: [sid] },
            );
          }
        }
      }
      const primary = current?.id || model;
      if (primary) {
        setSelectedModelIds((prev) => (prev.length <= 1 ? prev : [primary]));
      }
    }
    if (next.codeInterpreter) {
      const current = models.find((m) => m.id === model);
      if (current && !modelSupportsCodeInterpreter(current)) {
        const fallback = findCodeInterpreterFallbackModel(models);
        const reason = codeInterpreterBlockedReason(current);
        if (fallback) {
          setChatError(
            `${current.name} is not available for Code Interpreter${
              reason ? ` (${reason})` : ""
            }. Switched to ${fallback.name}.`,
          );
          pickModel(fallback.id);
          return;
        }
        if (reason) setChatError(reason);
      }
      setSelectedModelIds((prev) => {
        const allowed = prev.filter((id) => {
          const found = models.find((m) => m.id === id);
          return !found || modelSupportsCodeInterpreter(found);
        });
        return allowed.length && allowed.length !== prev.length ? allowed : prev;
      });
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
    if (isBackgroundVideoRunning(sessionId)) return false;
    if (isBackgroundSpeechRunning(sessionId)) return false;
    if (streamingSessionsRef.current[sessionId]) return false;
    return !sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
  }

  function isSessionBusyForSend(sessionId: string): boolean {
    if (abortControllersRef.current[sessionId]) return true;
    if (isBackgroundImageRunning(sessionId)) return true;
    if (isBackgroundVideoRunning(sessionId)) return true;
    if (isBackgroundSpeechRunning(sessionId)) return true;
    if (streamingSessionsRef.current[sessionId]) return true;
    return sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
  }

  function clearStaleStreamingFlag(sessionId: string): void {
    if (!streamingSessionsRef.current[sessionId]) return;
    if (abortControllersRef.current[sessionId]) return;
    if (isBackgroundImageRunning(sessionId)) return;
    if (isBackgroundVideoRunning(sessionId)) return;
    if (isBackgroundSpeechRunning(sessionId)) return;
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

  function parseApiError(raw: string, status: number): ParsedChatApiError {
    try {
      const j = JSON.parse(raw) as {
        detail?: string | {
          message?: string;
          code?: string;
          retry_after_seconds?: number;
        };
        message?: string;
        code?: string;
        retry_after_seconds?: number;
      };
      const detail = j.detail;
      if (detail && typeof detail === "object") {
        return {
          message: detail.message || raw || `Request failed (${status})`,
          code: detail.code || j.code,
          retryAfterSeconds: detail.retry_after_seconds ?? j.retry_after_seconds,
        };
      }
      return {
        message:
          (typeof detail === "string" ? detail : undefined)
          || j.message
          || raw
          || `Request failed (${status})`,
        code: j.code,
        retryAfterSeconds: j.retry_after_seconds,
      };
    } catch {
      return { message: raw || `Request failed (${status})` };
    }
  }

  function stopGenerating(sessionId?: string | null) {
    const sid = sessionId || activeIdRef.current;
    if (!sid) return;

    stopBackgroundImageGeneration(sid);
    stopBackgroundVideoGeneration(sid);
    stopBackgroundSpeechGeneration(sid);
    const controller = abortControllersRef.current[sid];
    if (controller) {
      controller.abort();
      delete abortControllersRef.current[sid];
    }

    const localMsgs = getSessionMessages(sid);
    if (localMsgs.some((m) => m.content === IMAGE_PENDING_MARKER)) {
      applyMessages(sid, buildStoppedImageMessages(localMsgs));
    } else if (localMsgs.some((m) => m.content === VIDEO_PENDING_MARKER)) {
      applyMessages(sid, buildStoppedVideoMessages(localMsgs));
    } else if (localMsgs.some((m) => m.content === SPEECH_PENDING_MARKER)) {
      applyMessages(sid, buildStoppedSpeechMessages(localMsgs));
    } else {
      let lastUserIdx = -1;
      for (let i = 0; i < localMsgs.length; i += 1) {
        if (localMsgs[i]?.role === "user") lastUserIdx = i;
      }
      let changed = false;
      const stoppedAt = Date.now();
      const next = localMsgs.map((m, i) => {
        if (i <= lastUserIdx || m.role !== "assistant" || m.receivedAt != null) return m;
        changed = true;
        const content = (m.content || "").trim() ? m.content : "Generation stopped.";
        return { ...m, content, receivedAt: stoppedAt };
      });
      if (changed) applyMessages(sid, next);
    }

    setSessionStreaming(sid, false);
    setTurnPhase(sid, undefined);

    if (!sessionPrivateMode(sid) && isChatSessionOnServer(sid)) {
      const hadPendingImage = localMsgs.some((m) => m.content === IMAGE_PENDING_MARKER);
      const hadPendingVideo = localMsgs.some((m) => m.content === VIDEO_PENDING_MARKER);
      const hadPendingSpeech = localMsgs.some((m) => m.content === SPEECH_PENDING_MARKER);
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
          if (hadPendingImage || hadPendingVideo || hadPendingSpeech) {
            const stoppedText = hadPendingImage
              ? "Image generation stopped."
              : hadPendingVideo
              ? "Video generation stopped."
              : "Speech generation stopped.";
            void patchLastSessionMessageOnServer(sid, stoppedText, {
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
    // Prefer the live active thread — sessionsRef can lag right after creating a chat.
    if (sessionId === activeIdRef.current && messagesRef.current.length) {
      return messagesRef.current;
    }
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
    pinScrollToBottomRef.current = true;
    const turnSession = sessionsRef.current.find((s) => s.id === sessionId);
    const toolsForTurn =
      sessionId === activeIdRef.current ? chatToolsRef.current : sessionTools(turnSession);
    const specialistTurn =
      !sessionPrivateMode(sessionId)
      && agentSelectionForSession(sessionId) !== NO_AGENT_SELECTION;
    const willRouteToImage = !specialistTurn && willRoutePromptToImageGeneration(
      userMsg.content,
      toolsForTurn,
      validModel,
      prevMsgs,
    );
    const willRouteToVideo =
      !specialistTurn && willRoutePromptToVideoGeneration(toolsForTurn, validModel);
    const willRouteToSpeech =
      !specialistTurn && willRoutePromptToSpeechGeneration(toolsForTurn, validModel);
    // Media generation is always single-model (primary only).
    const turnModels =
      specialistTurn ||
      willRouteToImage ||
      willRouteToVideo ||
      willRouteToSpeech ||
      toolsForTurn.imageGeneration ||
      toolsForTurn.videoGeneration ||
      toolsForTurn.speechGeneration
        ? [validModel]
        : resolveTurnModels(validModel);
    const controller = new AbortController();
    abortControllersRef.current[sessionId] = controller;
    setSessionStreaming(sessionId, true);
    setTurnPhase(sessionId, toolsForTurn.webSearch ? "searching" : "preparing");

    // Image / video / speech generation stay primary-model only.
    if (willRouteToImage || willRouteToVideo || willRouteToSpeech) {
      const assistantClientMessageId = newClientMessageId();
      const next: ChatMessage[] = [
        ...prevMsgs,
        userMsg,
        {
          role: "assistant",
          content: "",
          clientMessageId: assistantClientMessageId,
          modelId: validModel.id,
          modelName: validModel.name,
        },
      ];
      flushSync(() => updateSessionMessages(sessionId, next));
      scrollAfterNewTurn(sessionId);
      patchDefaultTitleFromMessages(sessionId, next);
      try {
        await runChatTurn(sessionId, next, validModel, controller, turnBaseCount, {
          userMessage: userMsg,
          assistantClientMessageId,
        });
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
        const friendly = friendlyTurnError(err);
        const errAssistant: ChatMessage = {
          role: "assistant",
          content: `Error: ${friendly}`,
          receivedAt: Date.now(),
          clientMessageId: assistantClientMessageId,
          modelId: validModel.id,
          modelName: validModel.name,
        };
        const errMsgs: ChatMessage[] = [
          ...prevMsgs,
          userMsg,
          errAssistant,
        ];
        applyMessages(sessionId, errMsgs);
        if (!sessionPrivateMode(sessionId)) {
          void finalizeAssistantOnServer(sessionId, errAssistant.content, {
            receivedAt: errAssistant.receivedAt,
            modelId: validModel.id,
            modelName: validModel.name,
            clientMessageId: errAssistant.clientMessageId,
            userMessage: userMsg,
          }).catch((e) => reportSyncError(e, sessionId));
        }
        void scheduleSessionTitle(sessionId, validModel.id, errMsgs);
      } finally {
        delete abortControllersRef.current[sessionId];
        setSessionStreaming(sessionId, false);
      }
      return;
    }

    flushSync(() => applyMessages(sessionId, [...prevMsgs, userMsg]));
    scrollAfterNewTurn(sessionId);
    patchDefaultTitleFromMessages(sessionId, [...prevMsgs, userMsg]);

    try {
      for (let i = 0; i < turnModels.length; i += 1) {
        if (controller.signal.aborted) break;
        const turnModel = turnModels[i];
        const assistantClientMessageId = newClientMessageId();
        const placeholder: ChatMessage = {
          role: "assistant",
          content: "",
          clientMessageId: assistantClientMessageId,
          modelId: turnModel.id,
          modelName: turnModel.name,
        };
        const withPlaceholder = [...getSessionMessages(sessionId), placeholder];
        flushSync(() => applyMessages(sessionId, withPlaceholder));
        const isLast = i === turnModels.length - 1;
        try {
          await runChatTurn(
            sessionId,
            withPlaceholder,
            turnModel,
            controller,
            turnBaseCount,
            {
              userMessage: userMsg,
              assistantClientMessageId,
              includeUserMessage: i === 0,
            },
            {
              skipTitle: true,
              skipReconcile: !isLast,
              // Multi-model text siblings must never fan out to /api/images.
              allowImageRoute: false,
            },
          );
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          const friendly = friendlyTurnError(err);
          const current = getSessionMessages(sessionId);
          const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
          const errAssistant: ChatMessage = {
            role: "assistant",
            content: `Error: ${friendly}`,
            receivedAt: Date.now(),
            clientMessageId: assistantClientMessageId,
            modelId: turnModel.id,
            modelName: turnModel.name,
          };
          const errMsgs =
            idx >= 0
              ? current.map((m, j) => (j === idx ? errAssistant : m))
              : [...current, errAssistant];
          applyMessages(sessionId, errMsgs);
          if (!sessionPrivateMode(sessionId)) {
            void finalizeAssistantOnServer(sessionId, errAssistant.content, {
              receivedAt: errAssistant.receivedAt,
              modelId: turnModel.id,
              modelName: turnModel.name,
              clientMessageId: errAssistant.clientMessageId,
              userMessage: i === 0 ? userMsg : undefined,
            }).catch((e) => reportSyncError(e, sessionId));
          }
        }
      }
      const finalMsgs = getSessionMessages(sessionId);
      void scheduleSessionTitle(sessionId, turnModels[0].id, finalMsgs);
      if (!sessionPrivateMode(sessionId)) {
        void fetchSessionWithMessages(sessionId).then((remote) => {
          if (!remote?.messages.length) return;
          if (activeIdRef.current !== sessionId && !sessionsRef.current.some((s) => s.id === sessionId)) {
            return;
          }
          const local = getLocalMessagesForSession(sessionId);
          // Never let an orphan server error-only thread wipe a local user prompt.
          if (
            local.some((m) => m.role === "user") &&
            !remote.messages.some((m) => m.role === "user") &&
            remote.messages.every(
              (m) => m.role === "assistant" && (m.content || "").startsWith("Error:"),
            )
          ) {
            return;
          }
          const reconciled = mergeChatMessagesPreferLocal(
            local,
            remote.messages,
            isLocalWorkInFlight(sessionId),
          );
          applyMessages(sessionId, reconciled);
        });
      }
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
      const friendly = friendlyTurnError(err);
      setChatError(friendly);
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

  async function downloadVideo(url: string) {
    const triggerDownload = (href: string) => {
      const safeHref = safeBrowserUrl(href, "download");
      if (!safeHref) throw new Error("Blocked unsafe video URL.");
      const a = document.createElement("a");
      a.href = safeHref;
      a.download = "alpha-router-generated-video.mp4";
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
      triggerDownload(url);
    } catch (err) {
      setChatError(formatApiError(err));
    }
  }

  async function downloadSpeech(url: string, format = "mp3") {
    const ext = (format || "mp3").replace(/[^a-z0-9]/gi, "") || "mp3";
    const triggerDownload = (href: string) => {
      const safeHref = safeBrowserUrl(href, "download");
      if (!safeHref) throw new Error("Blocked unsafe audio URL.");
      const a = document.createElement("a");
      a.href = safeHref;
      a.download = `alpha-router-generated-speech.${ext}`;
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
      triggerDownload(url);
    } catch (err) {
      setChatError(formatApiError(err));
    }
  }

  async function openVideoFullSize(url: string) {
    const openByAnchor = (href: string) => {
      if (!openSafeUrlInNewTab(href, "media")) {
        throw new Error("Blocked unsafe video URL.");
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
      openByAnchor(url);
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
        imageSizeTier: payload.imageSizeTier,
        routing: payload.routing,
        replaceIndex: msgIndex,
        fullMessages: messages,
        assistantClientMessageId: messages[msgIndex]?.clientMessageId,
      });
      if (!sessionPrivateMode(sid)) {
        await syncSessionsFromServer(sid);
      }
      setChatError("");
      maybeNotifyMediaReady(sid, messages[msgIndex]?.clientMessageId);
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

    // A generated image is persisted immediately after its user prompt. Retry
    // that turn with the concrete model and provider parameters that actually
    // produced the image; do not send Auto Router back through selection.
    const imageAfterPrompt =
      messages[index + 1]?.role === "assistant"
        ? parseImageMessage(messages[index + 1].content)
        : null;
    if (imageAfterPrompt) {
      const retryModelId = imageAfterPrompt.model?.trim();
      if (!retryModelId) {
        setChatError("The previous image request did not record a model.");
        return;
      }
      const tools = sessionTools(sessionsRef.current.find((x) => x.id === sid));
      setChatError("");
      setSessionStreaming(sid, true);
      try {
        await runBackgroundImageGeneration({
          sessionId: sid,
          historyWithUser: historyForModelRequest(messages.slice(0, index + 1)),
          localMessageBase: messages.slice(0, index + 1),
          prompt: imageAfterPrompt.prompt || target.content,
          modelId: retryModelId,
          privateMode: sessionPrivateMode(sid),
          referenceImage: imageAfterPrompt.reference_image,
          imageAspectPreset: tools.imageAspectRatio,
          imageCustomAspectRatio: tools.imageCustomAspectRatio,
          imageCustomSize: tools.imageCustomSize,
          regenerateFrom: {
            aspectRatio: imageAfterPrompt.aspectRatio,
            aspectPreset: imageAfterPrompt.aspectPreset,
            size: imageAfterPrompt.size,
          },
          imageSizeTier: imageAfterPrompt.imageSizeTier,
          routing: imageAfterPrompt.routing,
          replaceIndex: index + 1,
          fullMessages: messages,
          assistantClientMessageId: messages[index + 1]?.clientMessageId,
        });
        if (!sessionPrivateMode(sid)) await syncSessionsFromServer(sid);
        maybeNotifyMediaReady(sid, messages[index + 1]?.clientMessageId);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setChatError(message);
        if (!sessionPrivateMode(sid)) await syncSessionsFromServer(sid);
      } finally {
        setSessionStreaming(sid, false);
      }
      return;
    }

    const validModel =
      models.find((m) => m.id === model) ||
      models.find((m) => m.external_id === model) ||
      models[0];
    if (!validModel) {
      setChatError("No model available.");
      return;
    }
    if (validModel.id !== model) pickModel(validModel.id);

    const toolsForRetry =
      sid === activeIdRef.current
        ? chatToolsRef.current
        : sessionTools(sessionsRef.current.find((s) => s.id === sid));
    const willRouteToImage = willRoutePromptToImageGeneration(
      target.content,
      toolsForRetry,
      validModel,
      messages.slice(0, index),
    );
    const willRouteToVideo = willRoutePromptToVideoGeneration(toolsForRetry, validModel);
    const willRouteToSpeech = willRoutePromptToSpeechGeneration(toolsForRetry, validModel);
    const turnModels =
      willRouteToImage ||
      willRouteToVideo ||
      willRouteToSpeech ||
      toolsForRetry.imageGeneration ||
      toolsForRetry.videoGeneration ||
      toolsForRetry.speechGeneration
        ? [validModel]
        : resolveTurnModels(validModel);
    const base = messages.slice(0, index);
    const turnBaseCount = base.length;
    const userMsg: ChatMessage = {
      role: "user",
      content: target.content,
      sentAt: Date.now(),
      clientMessageId: newClientMessageId(),
    };
    pinScrollToBottomRef.current = true;
    const controller = new AbortController();
    abortControllersRef.current[sid] = controller;
    setSessionStreaming(sid, true);
    setChatError("");

    if (willRouteToImage || willRouteToVideo || willRouteToSpeech) {
      const assistantClientMessageId = newClientMessageId();
      const next: ChatMessage[] = [
        ...base,
        userMsg,
        {
          role: "assistant",
          content: "",
          clientMessageId: assistantClientMessageId,
          modelId: validModel.id,
          modelName: validModel.name,
        },
      ];
      flushSync(() => applyMessages(sid, next));
      scrollAfterNewTurn(sid);
      try {
        await runChatTurn(sid, next, validModel, controller, turnBaseCount, {
          userMessage: userMsg,
          assistantClientMessageId,
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setChatError(friendlyTurnError(err));
      } finally {
        delete abortControllersRef.current[sid];
        setSessionStreaming(sid, false);
      }
      return;
    }

    flushSync(() => applyMessages(sid, [...base, userMsg]));
    scrollAfterNewTurn(sid);

    try {
      for (let i = 0; i < turnModels.length; i += 1) {
        if (controller.signal.aborted) break;
        const turnModel = turnModels[i];
        const assistantClientMessageId = newClientMessageId();
        const placeholder: ChatMessage = {
          role: "assistant",
          content: "",
          clientMessageId: assistantClientMessageId,
          modelId: turnModel.id,
          modelName: turnModel.name,
        };
        const withPlaceholder = [...getSessionMessages(sid), placeholder];
        flushSync(() => applyMessages(sid, withPlaceholder));
        const isLast = i === turnModels.length - 1;
        try {
          await runChatTurn(
            sid,
            withPlaceholder,
            turnModel,
            controller,
            turnBaseCount,
            {
              userMessage: userMsg,
              assistantClientMessageId,
              includeUserMessage: i === 0,
            },
            {
              skipTitle: true,
              skipReconcile: !isLast,
              allowImageRoute: false,
            },
          );
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          const friendly = friendlyTurnError(err);
          const current = getSessionMessages(sid);
          const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
          const errAssistant: ChatMessage = {
            role: "assistant",
            content: `Error: ${friendly}`,
            receivedAt: Date.now(),
            clientMessageId: assistantClientMessageId,
            modelId: turnModel.id,
            modelName: turnModel.name,
          };
          const errMsgs =
            idx >= 0
              ? current.map((m, j) => (j === idx ? errAssistant : m))
              : [...current, errAssistant];
          applyMessages(sid, errMsgs);
          if (!sessionPrivateMode(sid)) {
            void finalizeAssistantOnServer(sid, errAssistant.content, {
              receivedAt: errAssistant.receivedAt,
              modelId: turnModel.id,
              modelName: turnModel.name,
              clientMessageId: errAssistant.clientMessageId,
              userMessage: i === 0 ? userMsg : undefined,
            }).catch((e) => reportSyncError(e, sid));
          }
        }
      }
      const finalMsgs = getSessionMessages(sid);
      void scheduleSessionTitle(sid, turnModels[0].id, finalMsgs);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setChatError(friendlyTurnError(err));
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
    const sid = activeIdRef.current || ensureActiveSession();
    if (sid && sessionPrivateMode(sid)) {
      throw new Error("No speech detected in Private Mode. Try again or type your message.");
    }

    // Layer 2: prefer the server (Whisper) over the browser fallback.
    let baseTranscript = "";
    const fd = new FormData();
    fd.append("file", blob, `voice-${Date.now()}.${extension}`);
    if (sid) fd.append("chat_session_id", sid);
    fd.append("language", voiceRecordingLang);
    try {
      const res = await authFetch("/api/chat/voice", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) throw new Error(parseApiError(await res.text(), res.status).message);
      const data = (await res.json()) as { transcript?: string };
      baseTranscript = (data.transcript || "").trim();
    } catch (err) {
      if (browserFallback.trim()) {
        baseTranscript = browserFallback.trim();
      } else {
        throw err;
      }
    }
    if (!baseTranscript && browserFallback.trim()) {
      baseTranscript = browserFallback.trim();
    }
    if (!baseTranscript) {
      throw new Error("No speech detected. Try again or type your message.");
    }

    // Layer 4: LLM refinement using conversation context (best-effort).
    try {
      const context = buildVoiceRefineContext();
      const refined = await refineVoiceTranscript(baseTranscript, model || "", context);
      if (refined && refined.trim()) return refined.trim();
    } catch {
      /* fall back to the base transcript */
    }
    return baseTranscript;
  }

  function buildVoiceRefineContext(): Array<{ role: string; content: string }> {
    const recent = messages.slice(-6);
    const out: Array<{ role: string; content: string }> = [];
    for (const m of recent) {
      const content = (m.content || "").trim();
      if (!content) continue;
      out.push({
        role: m.role === "assistant" ? "assistant" : "user",
        content: content.length > 300 ? content.slice(0, 300) + "…" : content,
      });
    }
    return out;
  }

  async function refineVoiceTranscript(
    transcript: string,
    modelRef: string,
    context: Array<{ role: string; content: string }>,
  ): Promise<string> {
    const data = await api<{ transcript?: string }>("/api/chat/voice/refine", {
      method: "POST",
      body: JSON.stringify({ transcript, model: modelRef || null, context }),
    });
    return (data.transcript || "").trim();
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
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      voiceStreamRef.current = stream;
      const { mimeType, extension } = pickVoiceRecordingMime();
      const recorderOpts: MediaRecorderOptions = mimeType
        ? { mimeType, audioBitsPerSecond: 128000 }
        : { audioBitsPerSecond: 128000 };
      const recorder = new MediaRecorder(stream, recorderOpts);
      voiceChunksRef.current = [];
      const speech = new BrowserSpeechCapture();
      browserSpeechRef.current = speech;
      speech.start(voiceRecordingLang);

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
    if (pendingAttachments.length + files.length > maxAttachments) {
      setChatError(`You can attach up to ${maxAttachments} files at once.`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setAttachUploading(true);
    setChatError("");
    try {
      if (sid && sessionPrivateMode(sid)) {
        const localAttachments = await processAttachmentFilesLocally(files);
        setPendingAttachments((prev) => [...prev, ...localAttachments].slice(0, maxAttachments));
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
        if (!res.ok) throw new Error(parseApiError(await res.text(), res.status).message);
        const data = (await res.json()) as { attachments: ProcessedAttachment[] };
        setPendingAttachments((prev) => [...prev, ...data.attachments].slice(0, maxAttachments));
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
    const validModel = resolvePromptAssistModel(models, model);
    if (!validModel) {
      setChatError("No text model is available for translation. Enable one in Admin → Models.");
      return;
    }
    // Video prompts want the same visual-prompt phrasing as image prompts.
    const assistContext =
      chatTools.imageGeneration || chatTools.videoGeneration || chatTools.speechGeneration
        ? "image"
        : "chat";
    setTranslateToEngBusy(true);
    setChatError("");
    try {
      const enhanced = await enhancePrompt(validModel.id, text, "translate", assistContext);
      if (!enhanced) {
        setChatError("Couldn't translate to English. Try again or send as is.");
        return;
      }
      // Treat unchanged / still-non-English output as failure (backend may also reject).
      if (enhanced.trim() === text || textNeedsEnglishTranslation(enhanced)) {
        setChatError("Couldn't translate to English. Try another text model or send as is.");
        return;
      }
      const dir = inputDirectionForText(enhanced, enhanced.length);
      setInput(enhanced);
      setInputDirection(dir);
      persistActiveComposerDraft({ text: enhanced, direction: dir });
      requestAnimationFrame(() => textareaRef.current?.focus());
    } catch (e) {
      const message = e instanceof Error && e.message ? e.message : "";
      setChatError(message || "Couldn't translate to English. Try again or send as is.");
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
    <div className="alpha-router-app" data-persian-font={persianFont || undefined}>
      <ChatModelPickerModal
        open={modelPickerMode != null}
        mode={modelPickerMode || "replace"}
        models={pickerModels}
        selectedIds={selectedModelIds}
        defaultModelId={defaultModel}
        onClose={() => setModelPickerMode(null)}
        onSelect={(id) =>
          modelPickerMode === "append" ? appendModelSelection(id) : replaceModelSelection(id)
        }
        onSetDefault={(id) => setAsDefaultModel(id)}
      />

      <div className="alpha-router-workspace">
      <aside className={`alpha-router-sidebar${selectedChatIds.size > 0 ? " is-selecting" : ""}`}>
        <div className="alpha-router-sidebar-top">
          <button
            type="button"
            className="alpha-router-icon-btn alpha-router-menu-btn"
            onClick={() => shellMenu?.openAdminMenu()}
            onMouseEnter={() => shellMenu?.openAdminMenu()}
            aria-label="Open menu"
            title="Menu"
          >
            ☰
          </button>
          <button type="button" className="alpha-router-new-chat" onClick={startNewChat} disabled={readOnly} title={readOnly ? "Read-only account" : undefined}>
            <span className="alpha-router-new-chat-icon">+</span>
            New chat
          </button>
        </div>
        <div className="alpha-router-sidebar-body">
          <>
            <input
              type="search"
              className="alpha-router-history-search"
              placeholder="Search chats…"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
            />
            {!readOnly && selectedChatIds.size > 0 ? (
              <div className="alpha-router-bulk-bar" role="toolbar" aria-label="Selected chats">
                <span className="alpha-router-bulk-bar__count">
                  {selectedChatIds.size} selected
                </span>
                <button
                  type="button"
                  className="alpha-router-bulk-bar__btn"
                  onClick={() => setMovingSessionIds([...selectedChatIds])}
                >
                  Move
                </button>
                <button
                  type="button"
                  className="alpha-router-bulk-bar__btn alpha-router-bulk-bar__btn--danger"
                  onClick={() => void deleteSelectedChats()}
                >
                  Delete
                </button>
                <div className="alpha-router-bulk-bar__secondary">
                  <button
                    type="button"
                    className="alpha-router-bulk-bar__btn"
                    onClick={selectAllVisibleChats}
                    disabled={
                      filteredSessions.length > 0 &&
                      filteredSessions.every((s) => selectedChatIds.has(s.id))
                    }
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    className="alpha-router-bulk-bar__btn"
                    onClick={clearChatSelection}
                  >
                    Clear
                  </button>
                </div>
              </div>
            ) : null}
            {!readOnly && (
            <div className="alpha-router-folder-create">
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

            <div className="alpha-router-folder-group">
              {folders.map((f) => (
                <div
                  key={f.id}
                  className={`alpha-router-folder-row${dropFolderId === f.id ? " is-drop-target" : ""}${f.color ? " has-color" : ""}`}
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
                    if (
                      draggingSessionId &&
                      selectedChatIds.size > 0 &&
                      selectedChatIds.has(draggingSessionId)
                    ) {
                      moveSessionsToFolder([...selectedChatIds], f.id);
                    } else if (draggingSessionId) {
                      moveSessionToFolder(draggingSessionId, f.id);
                    }
                  }}
                >
                  <div className="alpha-router-folder-title">
                    <button
                      type="button"
                      className="alpha-router-folder-toggle"
                      onClick={() => toggleFolderCollapse(f.id)}
                      aria-label={collapsedFolders[f.id] ? "Expand folder" : "Collapse folder"}
                      title={collapsedFolders[f.id] ? "Expand" : "Collapse"}
                    >
                      {collapsedFolders[f.id] ? "▸" : "▾"}
                    </button>
                    <span className="alpha-router-folder-icon" aria-hidden>
                      <IconFolder />
                    </span>
                    {renamingFolderId === f.id ? (
                      <form
                        className="alpha-router-folder-rename"
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
                        className="alpha-router-folder-title-actions"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <RowActionsMenu
                          label="Actions"
                          menuClassName="row-actions-menu--sidebar"
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
                    <ul className="alpha-router-history alpha-router-history-in-folder">
                      {(sessionsByFolder[f.id] || []).map((s) => renderSessionRow(s))}
                      {(sessionsByFolder[f.id] || []).length === 0 && (
                        <li className="alpha-router-history-empty">Drop chats here</li>
                      )}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
            {messageSearchHits.length > 0 && historySearch.trim().length >= 2 ? (
              <ul className="alpha-router-history alpha-router-history-search-hits">
                {messageSearchHits.map((hit) => (
                  <li key={`${hit.sessionId}-${hit.content.slice(0, 24)}`}>
                    <button
                      type="button"
                      className="alpha-router-history-item"
                      onClick={() => selectSession(hit.sessionId)}
                    >
                      <span className="alpha-router-history-item__subtitle">{hit.sessionTitle}</span>
                      {hit.content.slice(0, 80)}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="alpha-router-uncategorized-group">
              {inSearchMode ? (
                filteredSessions.length === 0 ? (
                  <p className="alpha-router-history-empty">No conversations</p>
                ) : (
                  <VirtualSidebarList
                    className="alpha-router-history-scroll"
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
                    <p className="alpha-router-history-empty">No conversations</p>
                  ) : (
                    <>
                      {todayRootSessions.length > 0 ? (
                        <>
                          <div className="alpha-router-history-section-label">Today</div>
                          <ul className="alpha-router-history alpha-router-history-scroll">
                            {todayRootSessions.map((s) => (
                              <li key={s.id}>{renderSessionRow(s)}</li>
                            ))}
                          </ul>
                        </>
                      ) : null}
                      {pastDaysRootSessions.length > 0 ? (
                        <div className="alpha-router-history-older">
                          <button
                            type="button"
                            className="alpha-router-history-older-toggle"
                            onClick={() => togglePastDaysSection()}
                            aria-expanded={pastDaysExpanded}
                          >
                            <span className="alpha-router-history-older-chevron">
                              {pastDaysExpanded ? "▾" : "▸"}
                            </span>
                            1–3 days ago ({pastDaysRootSessions.length})
                          </button>
                          {pastDaysExpanded ? (
                            <ul className="alpha-router-history alpha-router-history-scroll alpha-router-history-older-list">
                              {pastDaysRootSessions.map((s) => (
                                <li key={s.id}>{renderSessionRow(s)}</li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      ) : null}
                      {displayOlderCount > 0 ? (
                        <div className="alpha-router-history-older">
                          <button
                            type="button"
                            className="alpha-router-history-older-toggle"
                            onClick={() => toggleOlderSection()}
                            aria-expanded={olderExpanded}
                          >
                            <span className="alpha-router-history-older-chevron">
                              {olderExpanded ? "▾" : "▸"}
                            </span>
                            Older than 3 days ({displayOlderCount})
                          </button>
                          {olderExpanded ? (
                            olderLoading && olderRootSessions.length === 0 ? (
                              <p className="alpha-router-history-empty">Loading…</p>
                            ) : (
                              <>
                                <ul className="alpha-router-history alpha-router-history-scroll alpha-router-history-older-list">
                                  {olderRootSessions.map((s) => (
                                    <li key={s.id}>{renderSessionRow(s)}</li>
                                  ))}
                                </ul>
                                {olderLoadedCount < olderTotal ? (
                                  <button
                                    type="button"
                                    className="alpha-router-history-older-more"
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

      <div className="alpha-router-main-column">
      <div className="alpha-router-model-bar">
        <button
          type="button"
          className="alpha-router-add-model-btn"
          onClick={() => {
            setToolsMenuOpen(false);
            setModelPickerMode("append");
          }}
          disabled={
            !models.length ||
            (!chatTools.imageGeneration &&
              !chatTools.videoGeneration &&
              !chatTools.speechGeneration &&
              selectedModelIds.length >= MAX_MULTI_MODELS)
          }
          aria-label={
            chatTools.speechGeneration
              ? "Change speech model"
              : chatTools.videoGeneration
                ? "Change video model"
                : chatTools.imageGeneration
                  ? "Change image model"
                  : "Add model for multi-model response"
          }
          title={
            chatTools.speechGeneration
              ? "Text to Speech uses one model — picking another replaces it"
              : chatTools.videoGeneration
                ? "Video Generation uses one model — picking another replaces it"
                : chatTools.imageGeneration
                  ? "Image Generation uses one model — picking another replaces it"
                  : selectedModelIds.length >= MAX_MULTI_MODELS
                    ? `Maximum ${MAX_MULTI_MODELS} models`
                    : "Add model"
          }
        >
          <span aria-hidden>+</span>
          <span className="alpha-router-add-model-btn__label">Add Model</span>
          <span className="alpha-router-shortcut-keys" aria-hidden>
            <kbd className="alpha-router-kbd">{modKey === "⌘" ? "⌘" : "Ctrl"}</kbd>
            <kbd className="alpha-router-kbd">J</kbd>
          </span>
        </button>
        <div className="alpha-router-selected-models">
          {selectedModels.map((m) => (
            <span key={m.id} className="alpha-router-model-pill">
              <ModelProviderIcon modelId={m.external_id || m.id} size={14} />
              <span className="alpha-router-model-pill__name" title={m.name}>
                {shortModelName(m.name, m.id)}
              </span>
              <button
                type="button"
                className="alpha-router-model-pill__remove"
                onClick={() => removeSelectedModel(m.id)}
                aria-label={`Remove ${m.name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </div>

      <section className={`alpha-router-main${activePrivateMode ? " alpha-router-main--private" : ""}`}>
        {activePrivateMode ? <PrivateModeStrip /> : null}
        {readOnly && <ReadOnlyBanner className="readonly-account-banner--chat" />}
        {chatError && <div className="alpha-router-banner">{chatError}</div>}
        {modelsError && !chatError && <div className="alpha-router-banner alpha-router-banner-warn">{modelsError}</div>}
        {pendingHandoffs.map((handoff) => (
          <AgentHandoffBanner
            key={handoff.id}
            handoff={handoff}
            busy={handoffBusyId === handoff.id}
            onAccept={() => void handleAgentHandoff(handoff, "accept")}
            onDecline={() => void handleAgentHandoff(handoff, "decline")}
          />
        ))}

        <div className="alpha-router-messages" ref={messagesScrollRef}>
          {messagesLoadingOlder ? (
            <div className="alpha-router-banner alpha-router-banner-warn">Loading older messages…</div>
          ) : null}
          {messages.length === 0 && (
            <div className="alpha-router-welcome">
              <h2>{welcomeHeading}</h2>
            </div>
          )}
          {messages.map((m, i) => (
            <article
              key={`${activeId}-${i}`}
              className={`alpha-router-msg alpha-router-msg-${m.role}${m.modelId ? " alpha-router-msg-multi" : ""}`}
            >
              {m.role === "assistant" && m.agentName ? (
                <div
                  className="alpha-router-msg-agent-label"
                  title={m.agentId ? `Agent ${m.agentId}` : "Specialist Agent"}
                >
                  <span aria-hidden />
                  {m.agentName}
                </div>
              ) : null}
              {m.role === "assistant" && m.modelName ? (
                <div className="alpha-router-msg-model-label" title={m.modelId}>
                  <ModelName
                    modelId={m.modelId || m.modelName}
                    label={shortModelName(m.modelName, m.modelId || "")}
                    size={13}
                  />
                </div>
              ) : null}
              <div
                className="alpha-router-msg-inner"
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
                      <div className="alpha-router-generated-block alpha-router-generated-block--pending">
                        <div
                          className="alpha-router-generated-image alpha-router-generated-image--loading"
                          role="status"
                          aria-live="polite"
                          aria-label="Generating image"
                        >
                          <span className="alpha-router-image-loading__spinner" aria-hidden />
                          <span className="alpha-router-image-loading__label">Generating image…</span>
                        </div>
                      </div>
                    );
                  }
                  if (m.content === VIDEO_PENDING_MARKER) {
                    return (
                      <div className="alpha-router-generated-block alpha-router-generated-block--pending">
                        <div
                          className="alpha-router-generated-video alpha-router-generated-video--loading"
                          role="status"
                          aria-live="polite"
                          aria-label="Generating video"
                        >
                          <span className="alpha-router-image-loading__spinner" aria-hidden />
                          <span className="alpha-router-image-loading__label">Generating video…</span>
                        </div>
                      </div>
                    );
                  }
                  if (m.content === SPEECH_PENDING_MARKER) {
                    return (
                      <div className="alpha-router-generated-block alpha-router-generated-block--pending">
                        <div
                          className="alpha-router-generated-audio alpha-router-generated-audio--loading"
                          role="status"
                          aria-live="polite"
                          aria-label="Generating audio"
                        >
                          <span className="alpha-router-image-loading__spinner" aria-hidden />
                          <span className="alpha-router-image-loading__label">Generating speech…</span>
                        </div>
                      </div>
                    );
                  }
                  const imagePayload = readImageMessage(m.content);
                  if (imagePayload) {
                    return (
                      <div className="alpha-router-generated-block">
                        <AuthenticatedImage
                          url={imagePayload.url}
                          alt="Generated"
                          className="alpha-router-generated-image"
                        />
                      </div>
                    );
                  }
                  const videoPayload = readVideoMessage(m.content);
                  if (videoPayload) {
                    return (
                      <div className="alpha-router-generated-block">
                        <AuthenticatedVideo
                          url={videoPayload.url}
                          className="alpha-router-generated-video"
                          title={videoPayload.prompt || "Generated video"}
                        />
                      </div>
                    );
                  }
                  const speechPayload = readSpeechMessage(m.content);
                  if (speechPayload) {
                    return (
                      <div className="alpha-router-generated-block">
                        <AuthenticatedAudio
                          url={speechPayload.url}
                          title={speechPayload.prompt || "Generated speech"}
                          meta={{
                            voice: speechPayload.voice,
                            format: speechPayload.format,
                            durationSeconds: speechPayload.duration_seconds,
                            characters: speechPayload.characters,
                          }}
                        />
                      </div>
                    );
                  }
                  const mdImage = extractMarkdownImage(m.content || "");
                  if (mdImage.imageUrl) {
                    return (
                      <div className="alpha-router-generated-block">
                        <img
                          src={safeBrowserUrl(mdImage.imageUrl, "image") ?? ""}
                          alt="Generated"
                          className="alpha-router-generated-image"
                        />
                        {mdImage.text ? (
                          <MarkdownContent content={mdImage.text} className="alpha-router-markdown" />
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
                    const displayContent = formatAgentAnswerForDisplay(
                      fallback,
                      m.citations,
                    );
                    return (
                      <>
                        {showTurnStatus ? (
                          <p
                            className="alpha-router-turn-status"
                            aria-live="polite"
                            aria-label={`${turnPhaseLabel(activeTurnPhase)}...`}
                          >
                            <span className="alpha-router-turn-status__pulse" aria-hidden />
                            <span className="alpha-router-turn-status__label">
                              {turnPhaseLabel(activeTurnPhase)}
                              <TurnStatusDots />
                            </span>
                          </p>
                        ) : null}
                        {m.content?.trim() || !showTurnStatus ? (
                          <MarkdownContent
                            content={displayContent}
                            className={`alpha-router-markdown${streamingThisMessage ? " alpha-router-markdown--streaming" : ""}`}
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
              {m.role === "assistant" ? (
                <AgentCitationList
                  runId={m.agentRunId}
                  citations={m.citations}
                  onError={reportUserFacingApiError}
                />
              ) : null}
              <div className="alpha-router-msg-actions">
                {m.role === "assistant" &&
                typeof m.requestLogId === "number" &&
                m.content !== IMAGE_PENDING_MARKER &&
                m.content !== VIDEO_PENDING_MARKER &&
                m.content !== SPEECH_PENDING_MARKER &&
                !m.streaming &&
                !(isSessionStreaming && i === messages.length - 1) ? (
                  <MessageInfoButton
                    title="Cost details"
                    onClick={() => void openMessageCostDetails(m.requestLogId!)}
                  />
                ) : (
                  <MessageInfoButton title={chatMessageInfoTitle(m, m.role, messages, i)} />
                )}
                {(() => {
                  const videoPayload = readVideoMessage(m.content);
                  if (!videoPayload?.url) return null;
                  return (
                    <>
                      <button
                        type="button"
                        className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                        title="Download"
                        aria-label="Download video"
                        onClick={() => void downloadVideo(videoPayload.url)}
                      >
                        <DownloadIcon />
                      </button>
                      <button
                        type="button"
                        className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                        title="Open full size"
                        aria-label="Open video full size"
                        onClick={() => void openVideoFullSize(videoPayload.url)}
                      >
                        <OpenFullSizeIcon />
                      </button>
                    </>
                  );
                })()}
                {(() => {
                  const speechPayload = readSpeechMessage(m.content);
                  if (!speechPayload?.url) return null;
                  return (
                    <button
                      type="button"
                      className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                      title="Download"
                      aria-label="Download audio"
                      onClick={() => void downloadSpeech(speechPayload.url, speechPayload.format)}
                    >
                      <DownloadIcon />
                    </button>
                  );
                })()}
                {(() => {
                  const imagePayload = readImageMessage(m.content);
                  const mdImage = extractMarkdownImage(m.content || "");
                  const imageUrl = imagePayload?.url || mdImage.imageUrl || "";
                  if (!imageUrl) return null;
                  return (
                    <>
                      <button
                        type="button"
                        className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                        title="Download"
                        aria-label="Download image"
                        onClick={() => void downloadImage(imageUrl)}
                      >
                        <DownloadIcon />
                      </button>
                      <button
                        type="button"
                        className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                        title="Open full size"
                        aria-label="Open image full size"
                        onClick={() => void openImageFullSize(imageUrl)}
                      >
                        <OpenFullSizeIcon />
                      </button>
                      {imagePayload ? (
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                          title="Regenerate"
                          aria-label="Regenerate image"
                          disabled={isSessionStreaming}
                          onClick={() => regenerateImage(i, imagePayload)}
                        >
                          <RegenerateIcon />
                        </button>
                      ) : null}
                    </>
                  );
                })()}
                {m.role === "user" && (
                  <>
                    <button
                      type="button"
                      className="alpha-router-msg-action-btn"
                      onClick={() => void retryUserPromptAt(i)}
                      title="Retry"
                      aria-label="Retry prompt"
                    >
                      ↻
                    </button>
                    <button
                      type="button"
                      className="alpha-router-msg-action-btn"
                      onClick={() => void copyMessageContent(m.content, `${activeId}-${i}`)}
                    >
                      {copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy"}
                    </button>
                    <button
                      type="button"
                      className="alpha-router-msg-action-btn"
                      onClick={() => editUserPrompt(m.content)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="alpha-router-msg-action-btn"
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
                    m.content !== VIDEO_PENDING_MARKER &&
                    m.content !== SPEECH_PENDING_MARKER &&
                    !m.streaming &&
                    !(isSessionStreaming && i === messages.length - 1) ? (
                      <>
                        <button
                          type="button"
                          className={`alpha-router-msg-action-btn alpha-router-msg-feedback-btn${m.feedback?.rating === 1 ? " is-active" : ""}`}
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
                          className={`alpha-router-msg-action-btn alpha-router-msg-feedback-btn${m.feedback?.rating === -1 ? " is-active" : ""}`}
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
                      className="alpha-router-msg-action-btn"
                      onClick={() => void copyMessageContent(m.content, `${activeId}-${i}`)}
                    >
                      {copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy"}
                    </button>
                    {isTextAssistantExportable(m.content || "") ? (
                      <>
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                          title="Download CSV"
                          aria-label="Download CSV"
                          onClick={() => downloadCsv(`${activeId}-${i}`, m.content || "")}
                        >
                          <CsvIcon />
                        </button>
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                          title="Download PDF"
                          aria-label="Download PDF"
                          onClick={() => {
                            const title = (activeSession?.title || "chat-export").slice(0, 60);
                            void exportMessagePdf(m.content || "", title).catch((e) => {
                              console.error("PDF export failed", e);
                              alert(`PDF export failed: ${e?.message || e}`);
                            });
                          }}
                        >
                          <PdfIcon />
                        </button>
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                          title="Download Word"
                          aria-label="Download Word document"
                          onClick={() => {
                            const title = (activeSession?.title || "chat-export").slice(0, 60);
                            void exportMessageDocx(m.content || "", title).catch((e) => {
                              console.error("DOCX export failed", e);
                              alert(`DOCX export failed: ${e?.message || e}`);
                            });
                          }}
                        >
                          <DocIcon />
                        </button>
                        <button
                          type="button"
                          className="alpha-router-msg-action-btn alpha-router-msg-action-btn--icon"
                          title="Download TXT"
                          aria-label="Download plain text"
                          onClick={() => {
                            const title = (activeSession?.title || "chat-export").slice(0, 60);
                            downloadTxt(title, m.content || "");
                          }}
                        >
                          <TxtIcon />
                        </button>
                      </>
                    ) : null}
                  </>
                )}
              </div>
            </article>
          ))}
          <div ref={endRef} />
        </div>

        <footer className="alpha-router-footer">
          {readOnly ? (
            <div className="alpha-router-composer alpha-router-composer--readonly card">
              <p className="muted-text" style={{ margin: 0 }}>
                Read-only mode — browse your chat history above. Sending messages and using models is disabled.
              </p>
            </div>
          ) : (
          <form className="alpha-router-composer" onSubmit={send}>
            {showScrollToBottomBtn && messages.length > 0 ? (
              <button
                type="button"
                className="alpha-router-scroll-to-bottom"
                onClick={jumpToChatBottom}
                aria-label="Scroll to latest messages"
                title="Jump to bottom"
              >
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
            ) : null}
            <div
              className={`alpha-router-composer-box${agentModeActive ? " is-agent-active" : ""}`}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="alpha-router-file-input"
                accept={ATTACHMENT_ACCEPT}
                multiple
                onChange={(e) => void onAttachmentFilesSelected(e.target.files)}
                tabIndex={-1}
                aria-hidden
              />
              {pendingAttachments.length > 0 ? (
                <div className="alpha-router-pending-attachments">
                  {pendingAttachments.map((a, idx) => (
                    <span key={`${a.url}-${idx}`} className="alpha-router-pending-attachment">
                      <span className="alpha-router-pending-attachment__name" title={a.name}>
                        {a.kind === "image" ? "🖼" : "📄"} {a.name}
                      </span>
                      <button
                        type="button"
                        className="alpha-router-pending-attachment__remove"
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
                <div className="alpha-router-prompt-queue" aria-label="Queued messages">
                  {activeQueue.map((item, idx) => (
                    <div key={item.id} className="alpha-router-prompt-queue__item">
                      <span className="alpha-router-prompt-queue__index" aria-hidden>
                        {idx + 1}
                      </span>
                      <span className="alpha-router-prompt-queue__text" title={queueItemPreview(item)}>
                        {queueItemPreview(item)}
                      </span>
                      <div className="alpha-router-prompt-queue__actions">
                        <button
                          type="button"
                          className="alpha-router-prompt-queue__btn"
                          onClick={() => editQueuedPrompt(item)}
                          aria-label="Edit queued message"
                          title="Edit"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          className="alpha-router-prompt-queue__btn alpha-router-prompt-queue__btn--remove"
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
                className={`alpha-router-composer-input alpha-router-composer-input--${inputDirection}${showWelcomeComposerPrompt ? " alpha-router-composer-input--welcome-prompt" : ""}`}
                value={input}
                dir={inputDirection}
                onChange={onComposerInput}
                onSelect={onComposerSelect}
                onPaste={(e) => void onComposerPaste(e)}
                onKeyDown={onKeyDown}
                placeholder={composerPlaceholder}
                rows={1}
              />
              <div className="alpha-router-composer-bar">
                <div className="alpha-router-model-row">
                  <div className="alpha-router-tools-picker" ref={toolsMenuRef}>
                    <button
                      ref={toolsTriggerRef}
                      type="button"
                      className="alpha-router-composer-ctrl alpha-router-model-trigger alpha-router-tools-trigger--icon"
                      onClick={() => {
                        setModelPickerMode(null);
                        setToolsMenuOpen((o) => !o);
                      }}
                      aria-expanded={toolsMenuOpen}
                      aria-haspopup="menu"
                      aria-label="Tools"
                      title="Tools"
                    >
                      <span className="alpha-router-composer-ctrl__icon" aria-hidden>
                        <ComposerToolsIcon />
                      </span>
                      {activeToolCount > 0 ? (
                        <span className="alpha-router-composer-ctrl__badge">{activeToolCount}</span>
                      ) : null}
                    </button>
                  <ServerToolsMenu
                    open={toolsMenuOpen}
                    anchorRef={toolsTriggerRef}
                    tools={chatTools}
                    privateMode={activePrivateMode}
                    onChange={updateChatTools}
                    onPrivateModeChange={togglePrivateMode}
                    onClose={() => setToolsMenuOpen(false)}
                    videoCapabilities={selectedModels[0]}
                    speechCapabilities={selectedModels[0]}
                  />
                  </div>
                  <div className="alpha-router-tools-picker" ref={agentMenuRef}>
                    <button
                      ref={agentTriggerRef}
                      type="button"
                      className={`alpha-router-composer-ctrl alpha-router-agent-ctrl${agentModeActive ? " is-active" : ""}`}
                      onClick={() => {
                        setModelPickerMode(null);
                        setToolsMenuOpen(false);
                        setAgentMenuOpen((o) => !o);
                      }}
                      disabled={readOnly || activePrivateMode || !agentCatalog.length}
                      aria-expanded={agentMenuOpen}
                      aria-haspopup="menu"
                      aria-label="Agents"
                      title={
                        activePrivateMode
                          ? "Agents are unavailable in Private Mode because Agent runs and citations require server-side evidence."
                          : agentModeActive
                            ? `${activeAgentName || "Agent"} is on for this chat`
                            : "Turn on a governed specialist Agent for this chat"
                      }
                    >
                      <span className="alpha-router-composer-ctrl__icon" aria-hidden>
                        <ComposerAgentIcon />
                      </span>
                    </button>
                    <AgentMenu
                      open={agentMenuOpen}
                      anchorRef={agentTriggerRef}
                      agents={agentCatalog}
                      selection={activeAgentSelection}
                      disabled={readOnly || isSessionStreaming}
                      disabledReason={
                        isSessionStreaming
                          ? "Wait for the current answer to finish before changing Agents."
                          : undefined
                      }
                      onToggle={toggleAgentForActiveSession}
                      onClose={() => setAgentMenuOpen(false)}
                    />
                  </div>
                  <button
                    type="button"
                    className={`alpha-router-composer-ctrl alpha-router-translate-eng-btn${translateToEngBusy ? " is-busy" : ""}`}
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
                      <span className="alpha-router-composer-ctrl__spinner" aria-hidden />
                    ) : (
                      <span className="alpha-router-composer-ctrl__icon" aria-hidden>
                        <ComposerTranslateIcon />
                      </span>
                    )}
                    <span className="alpha-router-composer-ctrl__label">To ENG</span>
                  </button>
                </div>
                <div className="alpha-router-send-group">
                  {isStopVisible ? (
                    <button
                      type="button"
                      className="alpha-router-stop"
                      onClick={() => stopGenerating(activeId)}
                      aria-label="Stop generating"
                      title="Stop generating"
                    >
                      ■
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="alpha-router-attach-btn"
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
                    className={voiceRecording ? "alpha-router-stop alpha-router-voice-btn--recording" : "alpha-router-voice-btn"}
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
                    className="alpha-router-send"
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
          <p className="alpha-router-disclaimer">{PRODUCT_NAME} can make mistakes. Check important info.</p>
        </footer>
      </section>
      </div>
      </div>

      <ColorPickerModal
        open={!!colorPickerFolderId}
        title="Folder color"
        value={folders.find((f) => f.id === colorPickerFolderId)?.color ?? null}
        onClose={() => setColorPickerFolderId(null)}
        onChange={(color) => {
          if (colorPickerFolderId) setFolderColor(colorPickerFolderId, color);
        }}
      />

      <MoveToFolderModal
        open={!!movingSessionIds?.length}
        folders={folders}
        currentFolderId={
          movingSessionIds?.length === 1
            ? sessions.find((s) => s.id === movingSessionIds[0])?.folderId ?? null
            : null
        }
        onClose={() => setMovingSessionIds(null)}
        onMove={(folderId) => {
          if (movingSessionIds?.length) moveSessionsToFolder(movingSessionIds, folderId);
        }}
      />

      <RequestLogCostDetailsModal
        open={!!costDetailsLog}
        log={costDetailsLog}
        details={costDetails}
        loading={costDetailsLoading}
        error={costDetailsError}
        onClose={closeMessageCostDetails}
      />

    </div>
  );
}
