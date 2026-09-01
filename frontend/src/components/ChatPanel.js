import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { api, authFetch, formatApiError, getCachedSession, isApiAuthError } from "../api";
import { chatModelsEmptyMessage, normalizeChatModelsError } from "../lib/chatMessages";
import AuthenticatedImage from "./AuthenticatedImage";
import AuthenticatedVideo from "./AuthenticatedVideo";
import AuthenticatedAudio from "./AuthenticatedAudio";
import MarkdownContent from "./MarkdownContent";
import ModelName from "./ModelName";
import ReadOnlyBanner from "./ReadOnlyBanner";
import { useReadOnly } from "../context/ReadOnlyContext";
import { useShellMenu } from "../context/ShellMenuContext";
import { useChatModelChromeRegister } from "../context/ChatModelChromeContext";
import { useConfirm } from "../context/ConfirmContext";
import RowActionsMenu from "./RowActionsMenu";
import ColorPickerModal from "./ColorPickerModal";
import MoveToFolderModal from "./MoveToFolderModal";
import { IconFolder } from "./icons/navIcons";
import { fetchAuthenticatedMediaBlob, fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../lib/mediaUrl";
import { openSafeUrlInNewTab, safeBrowserUrl, } from "../lib/browserUrlPolicy";
import { createFolder, createSession, clearLocalChatStorage, DEFAULT_CHAT_TITLE, fetchUserChatsFromServer, fetchProjectChatById, fetchProjectChatSync, hydrateUserPrefsFromServer, fetchSessionWithMessages, isDefaultChatTitle, isPrivateChat, loadChatFoldersLocal, loadChatSessionsLocal, loadSessionMessagesIfNeeded, loadOlderSessionMessages, mergeSessionAfterMessageLoad, resolveNewChatModel, saveDefaultModelToServer, migrateLegacyChatsToServer, syncChatsToServer, deleteChatSessionOnServer, markPendingDelete, fetchChatSessionTitle, normalizeMessageForTitle, sessionTitleFromMessages, sessionTools, historyForModelRequest, mergeRemoteChatSessions, newClientMessageId, registerChatSessionsProvider, refreshChatsSince, commitServerListSync, shouldSkipEmptyIncrementalSync, registerImmediateChatSync, registerPrivateMessagesSync, finalizeAssistantOnServer, syncSessionMessagesToServer, cancelStreamingReplyOnServer, setMessageFeedbackOnServer, patchLastSessionMessageOnServer, clearSessionMessageSyncQueue, replaceChatSessionMessagesOnServer, isChatRevisionConflict, pollSessionMessagesFromServer, searchChatMessagesOnServer, isChatSessionOnServer, pushSessionMetadataToServer, markSessionMetadataDirty, setProjectChatScope, enhancePrompt, sessionActivityAt, withSessionMessagesActivity, sidebarTodayCutoffMs, sidebarOlderThan3DaysCutoffMs, sidebarOlderThan7DaysCutoffMs, sidebarHydrateMinActivityMs, } from "../lib/chatStorage";
import { PROJECT_MEDIA_ATTACH_EVENT, clearQueuedProjectMediaAttach, getProjectChatComposerPrefs, pinProjectChat, putProjectChatComposerPrefs, putProjectPrefs, readQueuedProjectMediaAttach, unpinProjectChat, } from "../lib/projectsApi";
import { emptyProjectChatComposerPrefs, overlayComposerPrefsOnSession, } from "../lib/projectChatComposer";
import { applyProjectChatSync, sortProjectSessions } from "../lib/projectChatSync";
import { CHAT_REFRESH_EVENT_NAME, onChatLeaderChange, } from "../lib/chatLeader";
import { formatLocalDateTimeFromMs } from "../lib/dateTime";
import { BROWSER_EVENT_NAMES, PRODUCT_NAME, STORAGE_KEYS } from "../lib/brand";
import { notifyReplyReady, REPLY_READY_FOCUS_EVENT, } from "../lib/replyReadyNotify";
import { getSessionUser, isSessionActive, logout } from "../lib/session";
import { copyFreshChatTools, anyChatToolEnabled, toolsToApiPayload } from "../lib/chatTools";
import MediaViewerModal from "./MediaViewerModal";
import ChatAttachmentMessage from "./chat/ChatAttachmentMessage";
import PromptQueue from "./chat/PromptQueue";
import { collectChatSlideshowItems } from "../lib/chatMediaViewer";
import { findMediaViewerIndex } from "../lib/mediaViewer";
import ChatAudioMessage from "./chat/ChatAudioMessage";
import ServerToolsMenu from "./chat/ServerToolsMenu";
import ChatModelPickerModal from "./chat/ChatModelPickerModal";
import ComposerAttachMenu from "./chat/ComposerAttachMenu";
import ComposerMediaPicker from "./chat/ComposerMediaPicker";
import ScreenshotCropOverlay from "./chat/ScreenshotCropOverlay";
import { ComposerAgentIcon, ComposerToolsIcon, ComposerTranslateIcon, } from "./chat/ComposerControlIcons";
import { MAX_MULTI_MODELS, } from "../lib/chatModelPresets";
import { DownloadIcon, OpenFullSizeIcon, RegenerateIcon, CsvIcon, PdfIcon, DocIcon, TxtIcon, } from "./chat/GeneratedImageIcons";
import RequestLogCostDetailsModal from "./RequestLogCostDetailsModal";
import { fetchOwnedRequestLog, fetchOwnedRequestLogCostDetails, } from "../lib/requestLogCostDetails";
import VirtualSidebarList from "./chat/ChatSidebarVirtual";
import PrivateModeLockIcon from "./chat/PrivateModeLockIcon";
import { BrowserSpeechCapture, pickVoiceRecordingMime } from "../lib/voiceInput";
import { ATTACHMENT_ACCEPT, AUDIO_MESSAGE_PREFIX, attachmentDisplayText, attachmentMessage, buildApiMessageContentAsync, cloneProcessedAttachments, compactChatMessagesForStorage, hasApiContent, DEFAULT_MAX_ATTACHMENTS, readAttachmentMessage, promptImpliesImageEdit, shouldRouteToImageGeneration, validateAttachmentFile, processAttachmentFilesLocally, } from "../lib/chatAttachments";
import { attachMediaIds } from "../lib/composerAttachSources";
import { captureDisplayFrame, revokeScreenshotFrame, screenshotPermissionErrorMessage, } from "../lib/screenshotCapture";
import { buildImageMessage, buildStoppedImageMessages, mergeChatMessagesPreferLocal, IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER, isBackgroundImageRunning, getBackgroundImageSessionIds, lastAssistantImageUrl, resolveImageGenerationReferenceAsync, runBackgroundImageGeneration, sessionHasInFlightGeneration, sessionHasPendingImage, sessionHasIncompleteTextReply, parseImageMessage, stopBackgroundImageGeneration, subscribeBackgroundImageUpdates, } from "../lib/chatImage";
import { findImageGenerationFallbackModel, modelSupportsImageToImage, modelSupportsImages, modelSupportsTextToImage, resolveImageGenerationModel as resolveConcreteImageModel, resolveSessionModelForTools, } from "../lib/chatImageModels";
import { isBackgroundVideoRunning, parseVideoMessage, runBackgroundVideoGeneration, shouldRouteToVideoGeneration, stopBackgroundVideoGeneration, subscribeBackgroundVideoUpdates, VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER, } from "../lib/chatVideo";
import { findVideoGenerationFallbackModel, modelSupportsVideos, resolveVideoGenerationModel as resolveConcreteVideoModel, resolveSessionModelForVideoTools, } from "../lib/chatVideoModels";
import { buildStoppedSpeechMessages, isBackgroundSpeechRunning, parseSpeechMessage, runBackgroundSpeechGeneration, shouldRouteToSpeechGeneration, SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER, stopBackgroundSpeechGeneration, subscribeBackgroundSpeechUpdates, } from "../lib/chatSpeech";
import { findSpeechGenerationFallbackModel, modelSupportsSpeech, resolveSpeechGenerationModel as resolveConcreteSpeechModel, resolveSessionModelForSpeechTools, resolveSpeechVoiceForModel, } from "../lib/chatSpeechModels";
import { codeInterpreterBlockedReason, findCodeInterpreterFallbackModel, modelSupportsCodeInterpreter, } from "../lib/chatCodeInterpreterModels";
import { findTextChatFallbackModel, isAutoRouterModel, modelSupportsTextChat, resolveDefaultModelPreference, resolvePromptAssistModel, } from "../lib/chatModels";
import { applyPersianFontToChat, normalizePersianFontId } from "../lib/persianFonts";
import { copyTextToClipboard } from "../lib/clipboard";
import { downloadCsv, downloadTxt, exportMessagePdf, exportMessageDocx } from "../lib/chatExport";
import { chatScrollJumpButtonVisible, pinAfterScrollEvent, scrollContainerToBottom, scrollPinFromViewport, } from "../lib/chatScroll";
import { clearComposerDraft, cloneComposerAttachments, getComposerDraft, syncComposerDraft, } from "../lib/composerDrafts";
import { inputDirectionForText, messageDirectionForText, textNeedsEnglishTranslation } from "../lib/textDirection";
import { isPrivateBlobRef, resolvePrivateBlobRef, } from "../lib/privateMediaStore";
import { COMPOSER_DEFAULT_PLACEHOLDER, COMPOSER_WELCOME_PROMPT, getChatWelcomeHeading, isReturningChatUser, shouldShowWelcomeComposerPrompt, } from "../lib/chatWelcome";
import { NO_AGENT_SELECTION, agentCompletionMetadataFromSse, agentRequestFields, decideAgentHandoff, fetchAgentCatalog, fetchPendingAgentHandoffs, formatAgentAnswerForDisplay, nextAgentSelection, resolveAgentSelection, } from "../lib/agentChat";
import { AgentCitationList, AgentHandoffBanner, } from "./chat/AgentExperience";
import AgentMenu from "./chat/AgentMenu";
function turnPhaseLabel(phase) {
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
    return (_jsxs("span", { className: "alpha-router-turn-status__dots", "aria-hidden": true, children: [_jsx("span", { className: "alpha-router-turn-status__dot", children: "." }), _jsx("span", { className: "alpha-router-turn-status__dot", children: "." }), _jsx("span", { className: "alpha-router-turn-status__dot", children: "." })] }));
}
function shortModelName(name, id) {
    const n = name || id;
    return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}
function imageMessage(payload) {
    return buildImageMessage(payload);
}
function audioMessage(payload) {
    return `${AUDIO_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}
function readAudioMessage(content) {
    if (content.startsWith(AUDIO_MESSAGE_PREFIX)) {
        try {
            return JSON.parse(content.slice(AUDIO_MESSAGE_PREFIX.length));
        }
        catch {
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
function removePromptThreadFromMessages(source, target, fallbackIndex) {
    let i = -1;
    if (target.clientMessageId) {
        i = source.findIndex((m) => m.clientMessageId === target.clientMessageId);
    }
    if (i < 0 && target.sentAt != null) {
        i = source.findIndex((m) => m.role === "user" && m.sentAt === target.sentAt);
    }
    if (i < 0 &&
        fallbackIndex != null &&
        source[fallbackIndex]?.role === "user" &&
        source[fallbackIndex]?.content === target.content) {
        i = fallbackIndex;
    }
    if (i < 0 || source[i]?.role !== "user")
        return null;
    const next = [...source];
    next.splice(i, 1);
    while (next[i]?.role === "assistant") {
        next.splice(i, 1);
    }
    return next;
}
function promptTextFromUserContent(content) {
    const attach = readAttachmentMessage(content);
    if (attach) {
        const text = attach.userText.trim();
        if (text)
            return text;
        if (attach.attachments.some((a) => a.kind === "image"))
            return "Edit this image";
        return attachmentDisplayText(attach);
    }
    const audio = readAudioMessage(content);
    if (audio?.transcript?.trim())
        return audio.transcript.trim();
    return content;
}
function displayTextForMessage(content) {
    const attach = readAttachmentMessage(content);
    if (attach)
        return attachmentDisplayText(attach);
    const audio = readAudioMessage(content);
    if (audio?.transcript)
        return audio.transcript;
    const image = readImageMessage(content);
    if (image?.prompt?.trim())
        return image.prompt.trim();
    const video = readVideoMessage(content);
    if (video?.prompt?.trim())
        return video.prompt.trim();
    const speech = readSpeechMessage(content);
    if (speech?.prompt?.trim())
        return speech.prompt.trim();
    return content;
}
function messageDirectionForContent(content) {
    if (content === IMAGE_PENDING_MARKER ||
        content.startsWith(IMAGE_MESSAGE_PREFIX) ||
        content === VIDEO_PENDING_MARKER ||
        content.startsWith(VIDEO_MESSAGE_PREFIX) ||
        content === SPEECH_PENDING_MARKER ||
        content.startsWith(SPEECH_MESSAGE_PREFIX)) {
        return "ltr";
    }
    const attach = readAttachmentMessage(content);
    if (attach) {
        return messageDirectionForText(attach.userText || attachmentDisplayText(attach));
    }
    const audio = readAudioMessage(content);
    if (audio?.transcript)
        return messageDirectionForText(audio.transcript);
    return messageDirectionForText(displayTextForMessage(content));
}
function readVideoMessage(content) {
    return parseVideoMessage(content);
}
function readSpeechMessage(content) {
    return parseSpeechMessage(content);
}
/** Last assistant slot is a speech placeholder still being generated. */
function messagesHavePendingSpeech(messages) {
    const last = messages.at(-1);
    return last?.role === "assistant" && last.content === SPEECH_PENDING_MARKER;
}
/** Last assistant slot is a video placeholder still being generated. */
function messagesHavePendingVideo(messages) {
    const last = messages.at(-1);
    return last?.role === "assistant" && last.content === VIDEO_PENDING_MARKER;
}
function buildStoppedVideoMessages(messages, stoppedText = "Video generation stopped.") {
    const withoutPending = messages.filter((m) => m.content !== VIDEO_PENDING_MARKER);
    const last = withoutPending.at(-1);
    if (last?.role === "assistant" && last.content === stoppedText)
        return withoutPending;
    return [
        ...withoutPending,
        { role: "assistant", content: stoppedText, receivedAt: Date.now() },
    ];
}
function readImageMessage(content) {
    if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
        try {
            return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length));
        }
        catch {
            return null;
        }
    }
    return null;
}
function newQueueId() {
    return `q-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
function queueItemPreview(item) {
    if (item.attachments.length) {
        const names = item.attachments.map((a) => a.name).join(", ");
        const text = item.text.trim();
        return text ? `${text} · ${names}` : names;
    }
    return item.text.trim() || "(empty)";
}
function extractMarkdownImage(content) {
    const re = /!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/i;
    const m = content.match(re);
    if (!m)
        return { imageUrl: null, text: content };
    const cleaned = content.replace(re, "").replace(/\n{3,}/g, "\n\n").trim();
    return { imageUrl: m[1], text: cleaned };
}
/** CSV / Word / PDF actions only for real text replies (not image/audio/pending). */
function isTextAssistantExportable(content) {
    if (!content?.trim())
        return false;
    if (content === IMAGE_PENDING_MARKER)
        return false;
    if (content === VIDEO_PENDING_MARKER)
        return false;
    if (content === SPEECH_PENDING_MARKER)
        return false;
    if (readImageMessage(content))
        return false;
    if (readVideoMessage(content))
        return false;
    if (readSpeechMessage(content))
        return false;
    if (readAudioMessage(content))
        return false;
    const md = extractMarkdownImage(content);
    if (md.imageUrl && !md.text.trim())
        return false;
    return true;
}
function formatChatMessageTime(ts) {
    return formatLocalDateTimeFromMs(ts);
}
function chatMessageInfoTitle(message, role, messages, index) {
    if (role === "user") {
        const sent = formatChatMessageTime(message.sentAt);
        return sent ? `Sent: ${sent}` : "Send time not recorded for this message.";
    }
    let promptSent = null;
    for (let j = index - 1; j >= 0; j -= 1) {
        if (messages[j].role === "user") {
            promptSent = formatChatMessageTime(messages[j].sentAt);
            break;
        }
    }
    const received = formatChatMessageTime(message.receivedAt);
    const lines = [];
    if (promptSent)
        lines.push(`Prompt sent: ${promptSent}`);
    if (received)
        lines.push(`Response received: ${received}`);
    return lines.length ? lines.join("\n") : "Timing not recorded for this message.";
}
function MessageInfoButton({ title, onClick, }) {
    return (_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--info", title: title, "aria-label": title, onClick: onClick, children: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "12", cy: "12", r: "10" }), _jsx("circle", { cx: "12", cy: "7", r: "1.65", fill: "currentColor", stroke: "none" }), _jsx("line", { x1: "12", y1: "10", x2: "12", y2: "18", strokeLinecap: "round" })] }) }));
}
function PrivateModeStrip() {
    return (_jsxs("div", { className: "alpha-router-private-strip", role: "status", children: [_jsx(PrivateModeLockIcon, { className: "alpha-router-private-strip__icon", size: 18 }), _jsxs("p", { className: "alpha-router-private-strip__text", children: [_jsx("span", { className: "alpha-router-private-strip__title", children: "Private Mode is ON" }), _jsxs("span", { className: "alpha-router-private-strip__sep", "aria-hidden": true, children: [" ", ":", " "] }), _jsxs("span", { className: "alpha-router-private-strip__body", children: ["Private Mode is permanent for this chat. Messages and media are stored only in this browser and will be ", _jsx("strong", { className: "alpha-router-private-strip__danger", children: "deleted" }), " when you log out or clear browser data."] })] })] }));
}
class ChatCompletionApiError extends Error {
    status;
    code;
    retryAfterSeconds;
    constructor(parsed, status) {
        super(parsed.message);
        this.name = "ChatCompletionApiError";
        this.status = status;
        this.code = parsed.code;
        this.retryAfterSeconds = parsed.retryAfterSeconds;
    }
}
export default function ChatPanel({ projectId, projectReadOnly = false, projectSidebarHeader, projectToolbar, projectBanner, mainOverride, enableModelChrome = true, hideChatSidebar = false, onProjectChatFocus, } = {}) {
    const accountReadOnly = useReadOnly();
    const readOnly = accountReadOnly || projectReadOnly;
    const isProjectChat = !!projectId;
    const navigate = useNavigate();
    const location = useLocation();
    const shellMenu = useShellMenu();
    const registerModelChrome = useChatModelChromeRegister();
    const { confirm } = useConfirm();
    const [models, setModels] = useState([]);
    const [modelsError, setModelsError] = useState("");
    const [model, setModel] = useState("");
    const [agentCatalog, setAgentCatalog] = useState([]);
    const [agentMenuOpen, setAgentMenuOpen] = useState(false);
    const [pendingHandoffs, setPendingHandoffs] = useState([]);
    const [handoffBusyId, setHandoffBusyId] = useState(null);
    /** Multi-model selection; send fans out to each id in order (primary = first). */
    const [selectedModelIds, setSelectedModelIds] = useState([]);
    const selectedModelIdsRef = useRef([]);
    selectedModelIdsRef.current = selectedModelIds;
    const selectedModelRef = useRef(model);
    selectedModelRef.current = model;
    const modelBeforeMediaToolsRef = useRef({});
    const [modelPickerMode, setModelPickerMode] = useState(null);
    const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
    const sessionUser = getSessionUser();
    const sessionUsername = sessionUser?.username ?? "";
    const welcomeName = sessionUser?.display_name || sessionUsername;
    const projectAuthorDisplayName = isProjectChat
        ? (sessionUser?.display_name || sessionUsername || "").trim() || undefined
        : undefined;
    const [chatTools, setChatTools] = useState(() => copyFreshChatTools());
    const chatToolsRef = useRef(chatTools);
    chatToolsRef.current = chatTools;
    const composerPrefCacheRef = useRef(new Map());
    const composerHydrateGenRef = useRef(0);
    const composerPrefSaveTimerRef = useRef(null);
    const [translateToEngBusy, setTranslateToEngBusy] = useState(false);
    const [defaultModel, setDefaultModel] = useState("");
    const [voiceRecordingLang, setVoiceRecordingLang] = useState("en");
    const [persianFont, setPersianFont] = useState("");
    /** False until user prefs hydrate (or fail) so we never stamp a catalog fallback before the saved default arrives. */
    const [userPrefsReady, setUserPrefsReady] = useState(false);
    const serverDefaultModelRef = useRef(undefined);
    const [historySearch, setHistorySearch] = useState("");
    const [serverSearchQuery, setServerSearchQuery] = useState("");
    const [messageSearchHits, setMessageSearchHits] = useState([]);
    const [sessionsTotal, setSessionsTotal] = useState(0);
    const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false);
    const [olderTotal, setOlderTotal] = useState(0);
    const [midDaysTotal, setMidDaysTotal] = useState(0);
    const [midDaysExpanded, setMidDaysExpanded] = useState(false);
    const [olderExpanded, setOlderExpanded] = useState(false);
    const [midDaysLoading, setMidDaysLoading] = useState(false);
    const [midDaysLoadingMore, setMidDaysLoadingMore] = useState(false);
    const [midDaysLoadedCount, setMidDaysLoadedCount] = useState(0);
    const [olderLoading, setOlderLoading] = useState(false);
    const [olderLoadingMore, setOlderLoadingMore] = useState(false);
    const [olderLoadedCount, setOlderLoadedCount] = useState(0);
    const [messagesLoadingOlder, setMessagesLoadingOlder] = useState(false);
    const [messagesHasOlder, setMessagesHasOlder] = useState(false);
    const [isLeaderTab, setIsLeaderTab] = useState(true);
    const serverSearchTimerRef = useRef(null);
    const [chatsHydrated, setChatsHydrated] = useState(false);
    const [hydrateOutcome, setHydrateOutcome] = useState("pending");
    const [sessions, setSessions] = useState([]);
    const [folders, setFolders] = useState([]);
    const [newFolderName, setNewFolderName] = useState("");
    const [collapsedFolders, setCollapsedFolders] = useState({});
    const [renamingFolderId, setRenamingFolderId] = useState(null);
    const [renamingFolderName, setRenamingFolderName] = useState("");
    const [renamingSessionId, setRenamingSessionId] = useState(null);
    const [renamingTitle, setRenamingTitle] = useState("");
    const [colorPickerFolderId, setColorPickerFolderId] = useState(null);
    const [movingSessionIds, setMovingSessionIds] = useState(null);
    const [selectedChatIds, setSelectedChatIds] = useState(() => new Set());
    const [activeId, setActiveId] = useState(null);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState("");
    const [inputDirection, setInputDirection] = useState("ltr");
    const composerInputRef = useRef("");
    const composerDirectionRef = useRef("ltr");
    const prevComposerSessionRef = useRef(null);
    const restoringComposerRef = useRef(false);
    const [streamingSessions, setStreamingSessions] = useState({});
    const [turnPhases, setTurnPhases] = useState({});
    const [chatError, setChatError] = useState("");
    const [copiedMessageKey, setCopiedMessageKey] = useState(null);
    const [costDetailsLog, setCostDetailsLog] = useState(null);
    const [costDetails, setCostDetails] = useState(null);
    const [costDetailsLoading, setCostDetailsLoading] = useState(false);
    const [costDetailsError, setCostDetailsError] = useState("");
    const [mediaViewerUrl, setMediaViewerUrl] = useState(null);
    const chatSlideshowItems = useMemo(() => collectChatSlideshowItems(messages), [messages]);
    const mediaViewerIndex = useMemo(() => (mediaViewerUrl ? findMediaViewerIndex(chatSlideshowItems, mediaViewerUrl) : -1), [mediaViewerUrl, chatSlideshowItems]);
    useEffect(() => {
        setMediaViewerUrl(null);
    }, [activeId]);
    useEffect(() => {
        if (mediaViewerUrl && mediaViewerIndex < 0)
            setMediaViewerUrl(null);
    }, [mediaViewerUrl, mediaViewerIndex]);
    const [draggingSessionId, setDraggingSessionId] = useState(null);
    const [dropFolderId, setDropFolderId] = useState(null);
    const endRef = useRef(null);
    const messagesScrollRef = useRef(null);
    const messagesInnerRef = useRef(null);
    const pinScrollToBottomRef = useRef(true);
    const userScrolledRef = useRef(false);
    const [showScrollToBottomBtn, setShowScrollToBottomBtn] = useState(false);
    const textareaRef = useRef(null);
    const toolsMenuRef = useRef(null);
    const toolsTriggerRef = useRef(null);
    const agentMenuRef = useRef(null);
    const agentTriggerRef = useRef(null);
    const activeIdRef = useRef(null);
    const lastSyncedActiveIdRef = useRef(null);
    const serverSaveTimerRef = useRef(null);
    const chatsHydratedRef = useRef(false);
    const hydrateGenRef = useRef(0);
    const foldersRef = useRef([]);
    const sessionsRef = useRef(sessions);
    const abortControllersRef = useRef({});
    const mediaRecorderRef = useRef(null);
    const voiceChunksRef = useRef([]);
    const voiceStreamRef = useRef(null);
    const browserSpeechRef = useRef(null);
    const fileInputRef = useRef(null);
    const attachBtnRef = useRef(null);
    const [attachMenuOpen, setAttachMenuOpen] = useState(false);
    const [mediaPickerOpen, setMediaPickerOpen] = useState(false);
    const [screenshotFrame, setScreenshotFrame] = useState(null);
    const screenshotFrameRef = useRef(null);
    const [voiceRecording, setVoiceRecording] = useState(false);
    const [voiceBusy, setVoiceBusy] = useState(false);
    const [pendingAttachments, setPendingAttachments] = useState([]);
    const [maxAttachments, setMaxAttachments] = useState(DEFAULT_MAX_ATTACHMENTS);
    const pendingAttachmentsRef = useRef([]);
    const [attachUploading, setAttachUploading] = useState(false);
    const [promptQueues, setPromptQueues] = useState({});
    const promptQueuesRef = useRef({});
    const [queueExpanded, setQueueExpanded] = useState(false);
    useEffect(() => {
        setQueueExpanded(false);
    }, [activeId]);
    const streamingSessionsRef = useRef({});
    const turnPhasesRef = useRef({});
    const streamingMsgsPendingRef = useRef(null);
    const streamingMsgsRafRef = useRef(null);
    const drainPromisesRef = useRef({});
    const drainSessionQueueRef = useRef(async () => { });
    const tryDrainPromptQueueRef = useRef(() => { });
    const messagesRef = useRef([]);
    const replyNotifyPrefsRef = useRef({ away: false, sound: true });
    activeIdRef.current = activeId;
    composerInputRef.current = input;
    composerDirectionRef.current = inputDirection;
    pendingAttachmentsRef.current = pendingAttachments;
    screenshotFrameRef.current = screenshotFrame;
    chatsHydratedRef.current = chatsHydrated;
    sessionsRef.current = sessions;
    foldersRef.current = folders;
    messagesRef.current = messages;
    const isSessionStreaming = activeId ? !!streamingSessions[activeId] : false;
    const isStopVisible = !!activeId &&
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
    const scrollChatToBottom = useCallback((behavior = "auto") => {
        const el = messagesScrollRef.current;
        if (el) {
            scrollContainerToBottom(el, behavior);
            return;
        }
        endRef.current?.scrollIntoView({ behavior });
    }, []);
    const syncScrollPinFromContainer = useCallback(() => {
        const el = messagesScrollRef.current;
        if (!el) {
            setShowScrollToBottomBtn(false);
            return;
        }
        pinScrollToBottomRef.current = scrollPinFromViewport(el);
        setShowScrollToBottomBtn(chatScrollJumpButtonVisible(el));
    }, []);
    const jumpToChatBottom = useCallback(() => {
        pinScrollToBottomRef.current = true;
        setShowScrollToBottomBtn(false);
        scrollChatToBottom("smooth");
    }, [scrollChatToBottom]);
    /** Scroll after the user bubble is painted so the turn stays in view. */
    const scrollAfterNewTurn = useCallback((sessionId) => {
        if (sessionId !== activeIdRef.current)
            return;
        pinScrollToBottomRef.current = true;
        setShowScrollToBottomBtn(false);
        requestAnimationFrame(() => {
            scrollChatToBottom("auto");
            requestAnimationFrame(() => scrollChatToBottom("auto"));
        });
    }, [scrollChatToBottom]);
    const pickerModels = useMemo(() => {
        const matched = models.filter((m) => {
            if (chatTools.imageGeneration && !modelSupportsImages(m, models))
                return false;
            if (chatTools.videoGeneration && !modelSupportsVideos(m, models))
                return false;
            if (chatTools.speechGeneration && !modelSupportsSpeech(m, models))
                return false;
            if (chatTools.codeInterpreter && !modelSupportsCodeInterpreter(m))
                return false;
            // Plain text chat: hide embeddings/rerank/media-only models that cannot answer chat.
            if (!chatTools.imageGeneration &&
                !chatTools.videoGeneration &&
                !chatTools.speechGeneration &&
                !modelSupportsTextChat(m)) {
                return false;
            }
            return true;
        });
        const autoRouter = matched.find((m) => isAutoRouterModel(m));
        if (!autoRouter)
            return matched;
        return [autoRouter, ...matched.filter((m) => m.id !== autoRouter.id)];
    }, [
        models,
        chatTools.imageGeneration,
        chatTools.videoGeneration,
        chatTools.speechGeneration,
        chatTools.codeInterpreter,
    ]);
    const selectedModels = useMemo(() => selectedModelIds
        .map((id) => models.find((m) => m.id === id))
        .filter((m) => !!m), [selectedModelIds, models]);
    const activeSession = activeId ? sessions.find((s) => s.id === activeId) : null;
    const activePrivateMode = isPrivateChat(activeSession);
    const activeSessionAgent = activeSession?.currentAgentId
        ? agentCatalog.find((agent) => agent.id === activeSession.currentAgentId)
        : undefined;
    const activeAgentSelection = activeId
        ? resolveAgentSelection(activeSession?.selectedAgentSlug, activeSessionAgent?.slug)
        : NO_AGENT_SELECTION;
    const agentModeActive = activeAgentSelection !== NO_AGENT_SELECTION;
    const activeAgentName = agentCatalog.find((agent) => agent.slug === activeAgentSelection)?.name || "";
    const activeToolCount = useMemo(() => {
        let n = 0;
        if (chatTools.webSearch)
            n += 1;
        if (chatTools.webFetch)
            n += 1;
        if (chatTools.imageGeneration)
            n += 1;
        if (chatTools.videoGeneration)
            n += 1;
        if (chatTools.speechGeneration)
            n += 1;
        if (chatTools.codeInterpreter)
            n += 1;
        if (activePrivateMode)
            n += 1;
        return n;
    }, [chatTools, activePrivateMode]);
    const inSearchMode = serverSearchQuery.length >= 2;
    const filteredSessions = useMemo(() => {
        const q = historySearch.trim().toLowerCase();
        if (!q)
            return sessions;
        return sessions.filter((s) => s.title.toLowerCase().includes(q));
    }, [sessions, historySearch]);
    const todayRootSessions = useMemo(() => {
        if (inSearchMode)
            return [];
        const todayStart = sidebarTodayCutoffMs();
        return filteredSessions
            .filter((s) => !s.folderId && sessionActivityAt(s) >= todayStart)
            .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
    }, [filteredSessions, inSearchMode]);
    const pastDaysRootSessions = useMemo(() => {
        if (inSearchMode)
            return [];
        const todayStart = sidebarTodayCutoffMs();
        const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
        return filteredSessions
            .filter((s) => {
            if (s.folderId)
                return false;
            const activity = sessionActivityAt(s);
            return activity >= threeDaysStart && activity < todayStart;
        })
            .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
    }, [filteredSessions, inSearchMode]);
    const midDaysRootSessions = useMemo(() => {
        if (inSearchMode)
            return [];
        const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
        const sevenDaysStart = sidebarOlderThan7DaysCutoffMs();
        return filteredSessions
            .filter((s) => {
            if (s.folderId)
                return false;
            const activity = sessionActivityAt(s);
            return activity >= sevenDaysStart && activity < threeDaysStart;
        })
            .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
    }, [filteredSessions, inSearchMode]);
    const olderRootSessions = useMemo(() => {
        if (inSearchMode)
            return [];
        const sevenDaysStart = sidebarOlderThan7DaysCutoffMs();
        return filteredSessions
            .filter((s) => !s.folderId && sessionActivityAt(s) < sevenDaysStart)
            .sort((a, b) => sessionActivityAt(b) - sessionActivityAt(a));
    }, [filteredSessions, inSearchMode]);
    const searchRootSessions = useMemo(() => (inSearchMode ? filteredSessions.filter((s) => !s.folderId) : []), [filteredSessions, inSearchMode]);
    const displayMidCount = useMemo(() => {
        if (inSearchMode)
            return 0;
        const threeDaysStart = sidebarOlderThan3DaysCutoffMs();
        const sevenDaysStart = sidebarOlderThan7DaysCutoffMs();
        const privateMid = sessions.filter((s) => {
            if (!isPrivateChat(s) || s.folderId)
                return false;
            const activity = sessionActivityAt(s);
            return activity >= sevenDaysStart && activity < threeDaysStart;
        }).length;
        return Math.max(midDaysTotal + privateMid, midDaysRootSessions.length);
    }, [sessions, midDaysTotal, midDaysRootSessions.length, inSearchMode]);
    const displayOlderCount = useMemo(() => {
        if (inSearchMode)
            return 0;
        const sevenDaysStart = sidebarOlderThan7DaysCutoffMs();
        const privateOlder = sessions.filter((s) => isPrivateChat(s) && !s.folderId && sessionActivityAt(s) < sevenDaysStart).length;
        return Math.max(Math.max(0, olderTotal) + privateOlder, olderRootSessions.length);
    }, [sessions, olderTotal, olderRootSessions.length, inSearchMode]);
    useEffect(() => {
        return onChatLeaderChange(setIsLeaderTab);
    }, []);
    useEffect(() => {
        const q = historySearch.trim();
        if (serverSearchTimerRef.current)
            window.clearTimeout(serverSearchTimerRef.current);
        if (q.length < 2) {
            setServerSearchQuery("");
            setMessageSearchHits([]);
            return;
        }
        serverSearchTimerRef.current = window.setTimeout(() => {
            setServerSearchQuery(q);
            void searchChatMessagesOnServer(q)
                .then((hits) => setMessageSearchHits(hits.map((h) => ({
                sessionId: h.sessionId,
                sessionTitle: h.sessionTitle,
                content: h.content,
            }))))
                .catch(() => setMessageSearchHits([]));
        }, 400);
        return () => {
            if (serverSearchTimerRef.current)
                window.clearTimeout(serverSearchTimerRef.current);
        };
    }, [historySearch]);
    useEffect(() => {
        if (!serverSearchQuery || serverSearchQuery.length < 2)
            return;
        let cancelled = false;
        void fetchUserChatsFromServer({ q: serverSearchQuery, limit: 30 })
            .then((remote) => {
            if (cancelled)
                return;
            setSessions((prev) => mergeRemoteChatSessions(prev, remote.sessions));
            setSessionsTotal(remote.total ?? remote.sessions.length);
        })
            .catch(() => { });
        return () => {
            cancelled = true;
        };
    }, [serverSearchQuery]);
    const rootSessions = searchRootSessions;
    const sessionsByFolder = useMemo(() => {
        const grouped = {};
        for (const s of filteredSessions) {
            if (!s.folderId)
                continue;
            if (!grouped[s.folderId])
                grouped[s.folderId] = [];
            grouped[s.folderId].push(s);
        }
        return grouped;
    }, [filteredSessions]);
    const currentModel = models.find((m) => m.id === model);
    function sessionPrivateMode(sessionId) {
        return isPrivateChat(sessionsRef.current.find((s) => s.id === sessionId));
    }
    function agentSelectionForSession(sessionId) {
        const session = sessionsRef.current.find((item) => item.id === sessionId);
        const bound = session?.currentAgentId
            ? agentCatalog.find((agent) => agent.id === session.currentAgentId)
            : undefined;
        return resolveAgentSelection(session?.selectedAgentSlug, bound?.slug);
    }
    /** Agents are mutually exclusive per chat; picking the active one turns it off. */
    function toggleAgentForActiveSession(slug) {
        const sessionId = activeIdRef.current || ensureActiveSession();
        if (!sessionId)
            return;
        const selection = nextAgentSelection(agentSelectionForSession(sessionId), slug);
        const cleared = selection === NO_AGENT_SELECTION;
        persistSessions((prev) => prev.map((s) => s.id === sessionId
            ? {
                ...s,
                selectedAgentSlug: cleared ? null : selection,
                // Drop the sticky binding so handoff polling and the next turn
                // both follow the user's choice to run without an Agent.
                ...(cleared
                    ? { currentAgentId: null, currentAgentVersionId: null }
                    : {}),
            }
            : s), { debounce: false });
        if (isProjectChat)
            scheduleComposerPrefSave(sessionId);
        if (!cleared) {
            const primary = selectedModelIdsRef.current[0] || model;
            if (primary)
                setSelectedModelIds([primary]);
        }
    }
    function applyAgentMetadataToSession(sessionId, metadata) {
        if (!metadata?.agentId)
            return;
        const selected = agentCatalog.find((agent) => agent.id === metadata.agentId);
        const next = sessionsRef.current.map((session) => session.id === sessionId
            ? {
                ...session,
                currentAgentId: metadata.agentId,
                currentAgentVersionId: metadata.agentVersionId ?? session.currentAgentVersionId,
                selectedAgentSlug: selected?.slug ?? session.selectedAgentSlug,
                agentSelectedAt: Date.now(),
            }
            : session);
        sessionsRef.current = next;
        setSessions(next);
    }
    async function handleAgentHandoff(handoff, decision) {
        setHandoffBusyId(handoff.id);
        setChatError("");
        try {
            const result = await decideAgentHandoff(handoff.id, decision);
            setPendingHandoffs((prev) => prev.filter((item) => item.id !== handoff.id));
            if (decision === "accept"
                && activeIdRef.current
                && result.agent_id
                && result.agent_slug) {
                const sessionId = activeIdRef.current;
                const next = sessionsRef.current.map((session) => session.id === sessionId
                    ? {
                        ...session,
                        currentAgentId: result.agent_id,
                        selectedAgentSlug: result.agent_slug,
                        agentSelectedAt: Date.now(),
                    }
                    : session);
                sessionsRef.current = next;
                setSessions(next);
            }
        }
        catch (error) {
            reportUserFacingApiError(error);
        }
        finally {
            setHandoffBusyId(null);
        }
    }
    /** Speech > video > image when multiple legacy flags survive a session payload. */
    function resolveModelForTools(sessionModel, tools) {
        const fallback = (current) => resolveNewChatModel(models, current, defaultModel);
        if (tools.speechGeneration) {
            return resolveSessionModelForSpeechTools(models, sessionModel, true, fallback);
        }
        if (tools.videoGeneration) {
            return resolveSessionModelForVideoTools(models, sessionModel, true, fallback);
        }
        return resolveSessionModelForTools(models, sessionModel, tools.imageGeneration, fallback);
    }
    function resolveModelForSession(session) {
        return resolveModelForTools(session.model, sessionTools(session));
    }
    function persistSessionModelCorrection(sessionId, modelId) {
        persistSessions((prev) => prev.map((s) => s.id === sessionId ? { ...s, model: modelId } : s), { debounce: false, metadataSessionIds: isProjectChat ? [] : [sessionId] });
        if (isProjectChat)
            return;
        if (!sessionPrivateMode(sessionId)) {
            void pushSessionMetadataToServer(sessionId).catch(() => { });
        }
    }
    function applyModelFromSession(session) {
        const resolved = resolveModelForSession(session);
        setModel(resolved);
        if (session.model !== resolved) {
            persistSessionModelCorrection(session.id, resolved);
        }
    }
    function isLocalTurnInFlight(sessionId) {
        return !!(abortControllersRef.current[sessionId] || streamingSessionsRef.current[sessionId]);
    }
    /**
     * True only while this tab itself is producing output (text stream fetch or
     * background image job). Unlike isLocalTurnInFlight it ignores the streaming
     * display flag, which is also set for server-side pending replies — gating
     * server polls on that flag would deadlock recovery (the poll sets the flag,
     * then blocks itself on it, so a stale pending marker never resolves).
     */
    function isLocalWorkInFlight(sessionId) {
        return (!!abortControllersRef.current[sessionId] ||
            isBackgroundImageRunning(sessionId) ||
            isBackgroundVideoRunning(sessionId) ||
            isBackgroundSpeechRunning(sessionId));
    }
    function getLocalMessagesForSession(sessionId) {
        if (sessionId === activeIdRef.current && messagesRef.current.length) {
            return messagesRef.current;
        }
        return sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
    }
    function preferLocalMessagesOverRemote(sessionId, remote) {
        return mergeChatMessagesPreferLocal(getLocalMessagesForSession(sessionId), remote, isLocalWorkInFlight(sessionId));
    }
    /** Surface API errors from user-initiated actions (send, delete, attach, …). */
    function reportUserFacingApiError(err) {
        if (isApiAuthError(err)) {
            setChatError("نشست شما منقضی شده است. در حال انتقال به صفحه ورود…");
            window.setTimeout(() => logout(), 1500);
            return;
        }
        setChatError(formatApiError(err));
    }
    /** Background sync failures must not block or alarm the user when the chat turn itself succeeded. */
    function reportSyncError(err, sessionId) {
        if (isChatRevisionConflict(err))
            return;
        if (sessionId && isBackgroundImageRunning(sessionId))
            return;
        if (sessionId && isBackgroundVideoRunning(sessionId))
            return;
        if (sessionId && isBackgroundSpeechRunning(sessionId))
            return;
        if (!sessionId && getBackgroundImageSessionIds().length > 0)
            return;
        if (sessionId && isLocalTurnInFlight(sessionId))
            return;
        if (sessionId && streamingSessionsRef.current[sessionId])
            return;
        if (!sessionId && Object.values(streamingSessionsRef.current).some(Boolean))
            return;
        if (isApiAuthError(err)) {
            logout();
            return;
        }
        console.warn("[alpha-router] background chat sync failed:", formatApiError(err));
    }
    const scheduleServerChatSave = useCallback((opts) => {
        const flush = () => {
            if (serverSaveTimerRef.current) {
                window.clearTimeout(serverSaveTimerRef.current);
                serverSaveTimerRef.current = null;
            }
            if (!chatsHydratedRef.current || readOnly)
                return;
            if (!getCachedSession())
                return;
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
        if (serverSaveTimerRef.current)
            window.clearTimeout(serverSaveTimerRef.current);
        serverSaveTimerRef.current = window.setTimeout(flush, 400);
    }, [readOnly]);
    const persistSessions = useCallback((next, opts) => {
        // Resolve against the live ref first. React may defer the setState updater,
        // and title/metadata push reads sessionsRef / the chatSessionsProvider.
        const resolved = typeof next === "function" ? next(sessionsRef.current) : next;
        sessionsRef.current = resolved;
        const metaIds = opts?.metadataSessionIds;
        if (metaIds?.length) {
            for (const id of metaIds) {
                const row = resolved.find((s) => s.id === id);
                if (row && !row.privateMode)
                    markSessionMetadataDirty(id);
            }
        }
        scheduleServerChatSave({ debounce: opts?.debounce !== false });
        setSessions(resolved);
    }, [scheduleServerChatSave]);
    function writeComposerOverlayLocal(overlaid) {
        const next = sessionsRef.current.map((row) => row.id === overlaid.id
            ? {
                ...row,
                tools: overlaid.tools,
                toolsTouched: overlaid.toolsTouched,
                model: overlaid.model,
                selectedAgentSlug: overlaid.selectedAgentSlug,
                currentAgentId: overlaid.currentAgentId,
                currentAgentVersionId: overlaid.currentAgentVersionId,
            }
            : row);
        sessionsRef.current = next;
        setSessions(next);
    }
    function scheduleComposerPrefSave(sessionId) {
        if (!isProjectChat || !projectId || readOnly)
            return;
        if (composerPrefSaveTimerRef.current) {
            window.clearTimeout(composerPrefSaveTimerRef.current);
        }
        composerPrefSaveTimerRef.current = window.setTimeout(() => {
            composerPrefSaveTimerRef.current = null;
            const session = sessionsRef.current.find((row) => row.id === sessionId);
            if (!session)
                return;
            const tools = sessionId === activeIdRef.current ? chatToolsRef.current : sessionTools(session);
            const prefs = {
                tools,
                toolsTouched: !!session.toolsTouched || anyChatToolEnabled(tools),
                model: (sessionId === activeIdRef.current
                    ? selectedModelRef.current || session.model
                    : session.model) || "",
                selectedAgentSlug: session.selectedAgentSlug ?? null,
            };
            composerPrefCacheRef.current.set(sessionId, prefs);
            void putProjectChatComposerPrefs(projectId, sessionId, {
                tools: prefs.tools,
                toolsTouched: prefs.toolsTouched,
                model: prefs.model,
                selectedAgentSlug: prefs.selectedAgentSlug ?? NO_AGENT_SELECTION,
            }).catch(() => { });
        }, 300);
    }
    function seedProjectComposerCache(session, tools) {
        if (!isProjectChat)
            return;
        composerPrefCacheRef.current.set(session.id, {
            tools: { ...tools },
            toolsTouched: !!session.toolsTouched,
            model: session.model || "",
            selectedAgentSlug: session.selectedAgentSlug ?? null,
        });
        scheduleComposerPrefSave(session.id);
    }
    function applyComposerFromSession(session) {
        if (!isProjectChat || !projectId) {
            applyModelFromSession(session);
            setChatTools(sessionTools(session));
            return;
        }
        const cached = composerPrefCacheRef.current.get(session.id);
        const overlaid = overlayComposerPrefsOnSession(session, cached ?? emptyProjectChatComposerPrefs());
        if (cached)
            writeComposerOverlayLocal(overlaid);
        applyModelFromSession(overlaid);
        setChatTools(sessionTools(overlaid));
        if (!cached) {
            const gen = ++composerHydrateGenRef.current;
            const sid = session.id;
            void getProjectChatComposerPrefs(projectId, sid)
                .then((prefs) => {
                if (gen !== composerHydrateGenRef.current)
                    return;
                composerPrefCacheRef.current.set(sid, prefs);
                if (activeIdRef.current !== sid)
                    return;
                const live = sessionsRef.current.find((row) => row.id === sid) || session;
                const next = overlayComposerPrefsOnSession(live, prefs);
                writeComposerOverlayLocal(next);
                applyModelFromSession(next);
                setChatTools(sessionTools(next));
            })
                .catch(() => {
                if (gen !== composerHydrateGenRef.current)
                    return;
                composerPrefCacheRef.current.set(sid, emptyProjectChatComposerPrefs());
            });
        }
    }
    const patchDefaultTitleFromMessages = useCallback((sid, msgs) => {
        const session = sessionsRef.current.find((s) => s.id === sid);
        if (!session || session.titleLocked || !isDefaultChatTitle(session.title))
            return;
        const title = sessionTitleFromMessages(msgs);
        if (isDefaultChatTitle(title))
            return;
        persistSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title } : s)), { debounce: false, metadataSessionIds: [sid] });
        if (!sessionPrivateMode(sid)) {
            void pushSessionMetadataToServer(sid).catch(() => { });
        }
    }, [persistSessions]);
    const applyLoadedSessionMessages = useCallback((sessionId, loaded) => {
        const live = sessionsRef.current.find((s) => s.id === sessionId);
        const merged = mergeSessionAfterMessageLoad(live, loaded);
        const next = sessionsRef.current.map((s) => (s.id === sessionId ? merged : s));
        sessionsRef.current = next;
        setSessions(next);
        patchDefaultTitleFromMessages(sessionId, merged.messages);
    }, [patchDefaultTitleFromMessages]);
    const updateSessionMessages = useCallback((sessionId, msgs) => {
        if (sessionId === activeIdRef.current) {
            messagesRef.current = msgs;
            setMessages(msgs);
        }
        const idx = sessionsRef.current.findIndex((s) => s.id === sessionId);
        if (idx < 0) {
            // New chat may not be in sessionsRef yet; keep messagesRef and retry on next write.
            return;
        }
        const next = sessionsRef.current.map((s, i) => i === idx ? withSessionMessagesActivity(s, msgs) : s);
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
        if (!pending)
            return;
        streamingMsgsPendingRef.current = null;
        const { sessionId, msgs } = pending;
        if (sessionId === activeIdRef.current) {
            messagesRef.current = msgs;
            setMessages(msgs);
        }
        const nextSessions = sessionsRef.current.map((s) => s.id === sessionId ? withSessionMessagesActivity(s, msgs) : s);
        sessionsRef.current = nextSessions;
        setSessions(nextSessions);
    }, []);
    const scheduleSessionTitle = useCallback(async (sid, modelId, msgs) => {
        const session = sessionsRef.current.find((s) => s.id === sid);
        if (!session || session.titleLocked || session.titleGenerated)
            return;
        const plainMsgs = msgs.map((m) => ({
            role: m.role,
            content: normalizeMessageForTitle(m.content),
        }));
        const fallback = sessionTitleFromMessages(plainMsgs);
        if (!isDefaultChatTitle(fallback)) {
            persistSessions((prev) => prev.map((s) => s.id === sid && isDefaultChatTitle(s.title) ? { ...s, title: fallback } : s), { debounce: false, metadataSessionIds: [sid] });
            if (!sessionPrivateMode(sid)) {
                await pushSessionMetadataToServer(sid);
            }
        }
        if (!msgs.some((m) => m.role === "assistant" && (m.content || "").trim()))
            return;
        const generated = await fetchChatSessionTitle(modelId, plainMsgs.slice(0, 6));
        let title = generated && !isDefaultChatTitle(generated) ? generated : fallback;
        if (generated &&
            !isDefaultChatTitle(fallback) &&
            generated.length < 4 &&
            fallback.length > generated.length) {
            title = fallback;
        }
        if (isDefaultChatTitle(title))
            return;
        persistSessions((prev) => prev.map((s) => {
            if (s.id !== sid)
                return s;
            if (s.titleLocked)
                return s;
            const current = (s.title || "").trim();
            if (!isDefaultChatTitle(current) &&
                current.length > title.length + 2 &&
                title.length < 4) {
                return s;
            }
            return { ...s, title, titleGenerated: true };
        }), { debounce: false, metadataSessionIds: [sid] });
        if (!sessionPrivateMode(sid)) {
            await pushSessionMetadataToServer(sid);
        }
    }, [persistSessions]);
    const persistFolders = useCallback((next) => {
        setFolders((prev) => {
            const resolved = typeof next === "function" ? next(prev) : next;
            foldersRef.current = resolved;
            scheduleServerChatSave({ debounce: false });
            return resolved;
        });
    }, [scheduleServerChatSave]);
    const applyMessages = useCallback((sessionId, msgs, opts) => {
        cancelStreamingMessagesFlush();
        updateSessionMessages(sessionId, msgs);
        if (opts?.debounce === false) {
            scheduleServerChatSave({ debounce: false });
        }
    }, [cancelStreamingMessagesFlush, updateSessionMessages, scheduleServerChatSave]);
    const syncSessionsFromServer = useCallback(async (sessionId) => {
        if (!chatsHydratedRef.current)
            return;
        try {
            const remote = await refreshChatsSince();
            if (remote.incremental && shouldSkipEmptyIncrementalSync(remote)) {
                return;
            }
            const protectedIds = new Set([
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
                }
                else if (!abortControllersRef.current[sid]) {
                    // Decide streaming from the locally-preferred view: a lagging server copy
                    // must not revive "generating" after the local turn already completed.
                    const decisionMsgs = preferLocalMessagesOverRemote(sid, s?.messages ?? []);
                    if (sessionHasIncompleteTextReply(decisionMsgs)) {
                        setSessionStreaming(sid, true);
                    }
                    else if (sessionHasPendingImage(decisionMsgs)) {
                        setSessionStreaming(sid, true);
                    }
                    else {
                        setSessionStreaming(sid, false);
                    }
                }
            }
        }
        catch {
            /* ignore refresh errors */
        }
    }, []);
    const deferSessionTitle = useCallback((sid, modelId, msgs) => {
        window.setTimeout(() => {
            void scheduleSessionTitle(sid, modelId, msgs);
        }, 1200);
    }, [scheduleSessionTitle]);
    const applyMessagesStreaming = useCallback((sessionId, msgs) => {
        streamingMsgsPendingRef.current = { sessionId, msgs };
        if (streamingMsgsRafRef.current != null)
            return;
        streamingMsgsRafRef.current = requestAnimationFrame(() => {
            flushStreamingMessages();
        });
    }, [flushStreamingMessages]);
    useEffect(() => {
        if (readOnly) {
            setModels([]);
            setModelsError("");
            setUserPrefsReady(true);
            return;
        }
        let cancelled = false;
        api("/api/chat/attachment-limits")
            .then((limits) => {
            if (cancelled)
                return;
            const count = Number(limits?.max_chat_attachments_count);
            if (Number.isFinite(count) && count >= 1) {
                setMaxAttachments(Math.min(50, Math.round(count)));
            }
        })
            .catch(() => {
            /* keep DEFAULT_MAX_ATTACHMENTS */
        });
        api("/api/chat/models", { cache: "no-store" })
            .then((m) => {
            if (cancelled)
                return;
            setModels(m);
            setModelsError(m.length ? "" : chatModelsEmptyMessage());
            if (!m.length)
                return;
            // Prefer the active session's stored model over the global default (stale
            // closure on model must not overwrite a per-chat selection after hydrate).
            const sid = activeIdRef.current;
            const sessionModel = (sid ? sessionsRef.current.find((s) => s.id === sid)?.model : "")?.trim() || "";
            setModel((prev) => {
                const prevTrim = (prev || "").trim();
                if (prevTrim && m.some((row) => row.id === prevTrim || row.external_id === prevTrim)) {
                    const match = m.find((row) => row.id === prevTrim || row.external_id === prevTrim);
                    return match?.id || prevTrim;
                }
                if (sessionModel) {
                    const match = m.find((row) => row.id === sessionModel || row.external_id === sessionModel);
                    return match?.id || sessionModel;
                }
                if (!userPrefsReady)
                    return prev;
                return resolveNewChatModel(m, prevTrim || undefined, defaultModel);
            });
        })
            .catch((e) => {
            if (cancelled)
                return;
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
            if (cancelled)
                return;
            setAgentCatalog(Array.isArray(catalog.items) ? catalog.items : []);
        })
            .catch(() => {
            if (cancelled)
                return;
            setAgentCatalog([]);
        });
        return () => {
            cancelled = true;
        };
    }, [readOnly, sessionUsername]);
    useEffect(() => {
        if (readOnly
            || !activeId
            || activePrivateMode
            || (activeAgentSelection === NO_AGENT_SELECTION
                && !activeSession?.currentAgentId)) {
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
        if (!models.length || !activeId || !chatsHydrated)
            return;
        const session = sessionsRef.current.find((s) => s.id === activeId);
        if (!session)
            return;
        const stored = (session.model || "").trim();
        // Per-chat model wins. Default is only for sessions that never chose a model.
        const resolved = resolveModelForTools(session.model, sessionTools(session));
        if (!resolved)
            return;
        setModel((prev) => (prev === resolved ? prev : resolved));
        // Persist only remaps (e.g. external_id → catalog id, image-tool swap) — never
        // replace a stored per-chat model with the user default after refresh.
        if (stored && stored !== resolved) {
            persistSessions((prev) => prev.map((s) => s.id === session.id ? { ...s, model: resolved } : s), { debounce: false, metadataSessionIds: [session.id] });
            if (!session.privateMode) {
                void pushSessionMetadataToServer(session.id).catch(() => { });
            }
        }
        else if (!stored && userPrefsReady && resolved) {
            // Brand-new session with empty model: stamp the resolved choice once.
            persistSessions((prev) => prev.map((s) => s.id === session.id ? { ...s, model: resolved } : s), { debounce: false, metadataSessionIds: [session.id] });
            if (!session.privateMode) {
                void pushSessionMetadataToServer(session.id).catch(() => { });
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
            if (cancelled)
                return;
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
            if (cancelled)
                return;
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
                .catch(() => { });
        }
        window.addEventListener(BROWSER_EVENT_NAMES.userPrefsSaved, onPrefsSaved);
        return () => window.removeEventListener(BROWSER_EVENT_NAMES.userPrefsSaved, onPrefsSaved);
    }, []);
    useEffect(() => {
        async function onChatsImported() {
            if (!chatsHydratedRef.current)
                return;
            try {
                const remote = await fetchUserChatsFromServer({ limit: 200 });
                const protectedIds = new Set([
                    ...Object.keys(streamingSessionsRef.current),
                    ...getBackgroundImageSessionIds(),
                ]);
                const merged = mergeRemoteChatSessions(sessionsRef.current, remote.sessions, protectedIds);
                sessionsRef.current = merged;
                commitServerListSync(merged);
                setSessions(merged);
                setFolders((prev) => {
                    const byId = new Map(prev.map((f) => [f.id, f]));
                    for (const f of remote.folders)
                        byId.set(f.id, f);
                    return [...byId.values()].sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
                });
                setSessionsTotal(remote.total ?? merged.length);
                if (remote.older_total != null)
                    setOlderTotal(remote.older_total);
                setHydrateOutcome(merged.length > 0 ? "ok" : "empty");
            }
            catch {
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
        if (!userPrefsReady || !models.length || !defaultModel)
            return;
        const resolved = resolveDefaultModelPreference(models, defaultModel);
        if (!resolved) {
            if (models.some((m) => m.id === defaultModel))
                return;
            setDefaultModel("");
            return;
        }
        if (resolved !== defaultModel) {
            setDefaultModel(resolved);
            void saveDefaultModelToServer(resolved)
                .then((saved) => setDefaultModel(saved || resolved))
                .catch(() => { });
        }
    }, [userPrefsReady, models, defaultModel]);
    useEffect(() => {
        if (!models.length || !model)
            return;
        if (models.some((m) => m.id === model))
            return;
        const byExternal = models.find((m) => m.external_id === model);
        if (byExternal) {
            setModel(byExternal.id);
            return;
        }
        // Prefer the active session's stored model over the global default.
        const sid = activeIdRef.current;
        const sessionModel = (sid ? sessionsRef.current.find((s) => s.id === sid)?.model : "")?.trim() || "";
        if (sessionModel) {
            const match = models.find((m) => m.id === sessionModel || m.external_id === sessionModel);
            if (match) {
                setModel(match.id);
                return;
            }
            // Keep the per-chat id even if temporarily missing from catalog.
            if (sessionModel === model)
                return;
            setModel(sessionModel);
            return;
        }
        if (!userPrefsReady)
            return;
        // No per-chat model — heal UI from default / catalog only.
        setModel(resolveNewChatModel(models, undefined, defaultModel));
    }, [userPrefsReady, models, model, defaultModel]);
    useEffect(() => {
        if (!models.length ||
            !model ||
            chatTools.imageGeneration ||
            chatTools.videoGeneration ||
            chatTools.speechGeneration) {
            return;
        }
        const current = models.find((m) => m.id === model || m.external_id === model);
        if (!current || modelSupportsTextChat(current))
            return;
        const fallback = findTextChatFallbackModel(models);
        if (!fallback || fallback.id === current.id)
            return;
        setModel(fallback.id);
        setSelectedModelIds((prev) => (prev.length <= 1 ? [fallback.id] : prev));
        const sid = activeIdRef.current || ensureActiveSession();
        if (sid) {
            persistSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, model: fallback.id } : s)), { debounce: false, metadataSessionIds: [sid] });
            if (!sessionPrivateMode(sid)) {
                void pushSessionMetadataToServer(sid).catch(() => { });
            }
        }
        setChatError(`${current.name} is not available for text chat. Switched to ${fallback.name}.`);
    }, [
        models,
        model,
        chatTools.imageGeneration,
        chatTools.videoGeneration,
        chatTools.speechGeneration,
    ]);
    useEffect(() => {
        setProjectChatScope(projectId || null);
        composerPrefCacheRef.current = new Map();
        return () => setProjectChatScope(null);
    }, [projectId]);
    useEffect(() => {
        const gen = ++hydrateGenRef.current;
        (async () => {
            try {
                const remote = await fetchUserChatsFromServer({
                    limit: 50,
                    min_activity_ms: sidebarHydrateMinActivityMs(),
                });
                if (gen !== hydrateGenRef.current)
                    return;
                const localSessions = isProjectChat ? [] : loadChatSessionsLocal();
                const localFolders = isProjectChat ? [] : loadChatFoldersLocal();
                let nextSessions = remote.sessions;
                let nextFolders = remote.folders;
                let recentTotal = remote.total ?? remote.sessions.length;
                let olderTotalValue = remote.older_total ?? 0;
                const lastOpenedSessionId = isProjectChat && typeof remote.lastOpenedSessionId === "string"
                    ? remote.lastOpenedSessionId
                    : null;
                const readOnlyNow = !isSessionActive();
                if (!isProjectChat &&
                    !readOnlyNow &&
                    !nextSessions.length &&
                    (localSessions.length || localFolders.length)) {
                    nextSessions = localSessions;
                    nextFolders = localFolders.length ? localFolders : remote.folders;
                    await migrateLegacyChatsToServer(nextSessions, nextFolders);
                    clearLocalChatStorage();
                    if (gen !== hydrateGenRef.current)
                        return;
                    const afterMigrate = await fetchUserChatsFromServer({
                        limit: 50,
                        min_activity_ms: sidebarHydrateMinActivityMs(),
                    });
                    if (gen !== hydrateGenRef.current)
                        return;
                    nextSessions = afterMigrate.sessions;
                    nextFolders = afterMigrate.folders;
                    recentTotal = afterMigrate.total ?? nextSessions.length;
                    olderTotalValue = afterMigrate.older_total ?? 0;
                }
                let midDaysTotalValue = 0;
                let midDaysLoaded = 0;
                let olderThan7Value = 0;
                if (!isProjectChat && olderTotalValue > 0) {
                    try {
                        const midRemote = await fetchUserChatsFromServer({
                            limit: 40,
                            min_activity_ms: sidebarOlderThan7DaysCutoffMs(),
                            max_activity_ms: sidebarOlderThan3DaysCutoffMs(),
                            retainKnownSessionIds: true,
                        });
                        if (gen !== hydrateGenRef.current)
                            return;
                        midDaysTotalValue = midRemote.total ?? 0;
                        midDaysLoaded = midRemote.fetchedCount ?? 0;
                        olderThan7Value = Math.max(0, olderTotalValue - midDaysTotalValue);
                        if (midRemote.sessions.length) {
                            nextSessions = mergeRemoteChatSessions(nextSessions, midRemote.sessions);
                        }
                    }
                    catch {
                        olderThan7Value = olderTotalValue;
                    }
                }
                sessionsRef.current = nextSessions;
                commitServerListSync(nextSessions);
                setSessions(nextSessions);
                setFolders(nextFolders);
                setSessionsTotal(recentTotal);
                setMidDaysTotal(midDaysTotalValue);
                setMidDaysLoadedCount(midDaysLoaded);
                setOlderTotal(olderThan7Value);
                setOlderLoadedCount(0);
                setMidDaysExpanded(false);
                setOlderExpanded(false);
                setMidDaysLoading(false);
                setMidDaysLoadingMore(false);
                setOlderLoading(false);
                setOlderLoadingMore(false);
                setChatsHydrated(true);
                setHydrateOutcome(nextSessions.length > 0 ? "ok" : "empty");
                setChatError("");
                const wantedParam = isProjectChat
                    ? new URLSearchParams(window.location.search).get("session")
                    : null;
                const wantedSessionId = (wantedParam || lastOpenedSessionId || "").trim() || null;
                if (nextSessions.length > 0 || (isProjectChat && wantedSessionId)) {
                    let first = (wantedSessionId && nextSessions.find((row) => row.id === wantedSessionId)) || null;
                    if (wantedSessionId && !first && projectId) {
                        const fetched = await fetchProjectChatById(projectId, wantedSessionId);
                        if (gen !== hydrateGenRef.current)
                            return;
                        if (fetched) {
                            nextSessions = sortProjectSessions([
                                fetched,
                                ...nextSessions.filter((row) => row.id !== fetched.id),
                            ]);
                            sessionsRef.current = nextSessions;
                            commitServerListSync(nextSessions);
                            setSessions(nextSessions);
                            setSessionsTotal(Math.max(recentTotal, nextSessions.length));
                            first = fetched;
                        }
                    }
                    if (!first)
                        first = nextSessions[0] || null;
                    if (!first) {
                        setHydrateOutcome("empty");
                    }
                    else {
                        if (nextSessions.length)
                            setHydrateOutcome("ok");
                        activeIdRef.current = first.id;
                        pinScrollToBottomRef.current = true;
                        setActiveId(first.id);
                        applyComposerFromSession(first);
                        if (!first.privateMode && !first.messages.length && (first.messageCount ?? 0) > 0) {
                            void loadSessionMessagesIfNeeded(first, { limit: 50 }).then((loaded) => {
                                if (gen !== hydrateGenRef.current || activeIdRef.current !== first.id)
                                    return;
                                setMessages(loaded.messages);
                                setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
                                if (sessionHasIncompleteTextReply(loaded.messages)) {
                                    setSessionStreaming(first.id, true);
                                }
                                applyLoadedSessionMessages(first.id, loaded);
                            });
                        }
                        else {
                            setMessages(first.messages);
                        }
                    }
                }
            }
            catch (err) {
                if (gen !== hydrateGenRef.current)
                    return;
                if (isProjectChat) {
                    setHydrateOutcome("error");
                    setChatError(err instanceof Error
                        ? err.message
                        : "Could not load project chats.");
                    setChatsHydrated(true);
                    return;
                }
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
                }
                else {
                    setHydrateOutcome("error");
                    setChatError(err instanceof Error
                        ? err.message
                        : "Could not load chat history. Try signing out and back in.");
                }
                setChatsHydrated(true);
            }
        })();
    }, [isProjectChat, projectId]);
    useEffect(() => {
        let debounceTimer;
        const onRefresh = () => {
            if (!chatsHydratedRef.current)
                return;
            if (debounceTimer)
                window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(() => {
                debounceTimer = undefined;
                void refreshChatsSince()
                    .then((remote) => {
                    if (shouldSkipEmptyIncrementalSync(remote)) {
                        return;
                    }
                    const protectedIds = new Set([
                        ...Object.keys(streamingSessionsRef.current),
                        ...getBackgroundImageSessionIds(),
                    ]);
                    const merged = mergeRemoteChatSessions(sessionsRef.current, remote.sessions, protectedIds);
                    sessionsRef.current = merged;
                    setSessions(merged);
                })
                    .catch(() => { });
            }, 400);
        };
        window.addEventListener(CHAT_REFRESH_EVENT_NAME, onRefresh);
        return () => {
            if (debounceTimer)
                window.clearTimeout(debounceTimer);
            window.removeEventListener(CHAT_REFRESH_EVENT_NAME, onRefresh);
        };
    }, []);
    useEffect(() => {
        if (!isProjectChat || !projectId || !chatsHydrated)
            return;
        const sid = activeId;
        if (!sid)
            return;
        const timer = window.setTimeout(() => {
            void putProjectPrefs(projectId, { lastOpenedSessionId: sid }).catch(() => { });
        }, 300);
        return () => window.clearTimeout(timer);
    }, [isProjectChat, projectId, activeId, chatsHydrated]);
    useEffect(() => {
        if (!isProjectChat || !projectId || !chatsHydrated)
            return;
        let cancelled = false;
        let inflight = false;
        let since;
        let previousSessionIds = sessionsRef.current.map((row) => row.id);
        const maxSequence = (msgs) => {
            let max = null;
            for (const msg of msgs) {
                if (typeof msg.sequence === "number") {
                    max = max == null ? msg.sequence : Math.max(max, msg.sequence);
                }
            }
            return max;
        };
        const tick = async () => {
            if (cancelled || inflight || document.hidden)
                return;
            inflight = true;
            try {
                const sid = activeIdRef.current;
                const localMsgs = sid && sid === activeIdRef.current
                    ? (messagesRef.current.length
                        ? messagesRef.current
                        : sessionsRef.current.find((row) => row.id === sid)?.messages ?? [])
                    : [];
                const lastSeq = sid ? maxSequence(localMsgs) : null;
                const skipMessages = !!(sid && isLocalWorkInFlight(sid));
                const remote = await fetchProjectChatSync(projectId, {
                    since,
                    sessionId: skipMessages ? null : sid,
                    afterSequence: skipMessages ? null : lastSeq,
                });
                if (cancelled)
                    return;
                since = remote.serverTimeMs;
                // Protect only this tab's in-flight work. The streaming *display* flag is
                // also set for other members watching a live reply; gating on it deadlocks
                // observers so they never receive assistant patches.
                const protectedIds = new Set(getBackgroundImageSessionIds());
                if (sid && isLocalWorkInFlight(sid))
                    protectedIds.add(sid);
                const { sessions: merged, activeMessages } = applyProjectChatSync(sessionsRef.current, remote, {
                    previousSessionIds,
                    protectedIds,
                    activeSessionId: sid,
                    incrementalMessages: lastSeq != null,
                    activeLocalMessages: localMsgs,
                });
                previousSessionIds = remote.sessionIds;
                let nextSessions = merged;
                if (sid && !merged.some((row) => row.id === sid)) {
                    sessionsRef.current = merged;
                    setSessions(merged);
                    const fallback = merged[0];
                    if (fallback) {
                        activeIdRef.current = fallback.id;
                        setActiveId(fallback.id);
                        setMessages(fallback.messages);
                    }
                    return;
                }
                if (sid &&
                    activeMessages &&
                    sid === activeIdRef.current &&
                    !isLocalWorkInFlight(sid)) {
                    const preferred = preferLocalMessagesOverRemote(sid, activeMessages);
                    setMessages(preferred);
                    if (!sessionHasInFlightGeneration(preferred)) {
                        setSessionStreaming(sid, false);
                    }
                    if (preferred !== activeMessages) {
                        nextSessions = merged.map((row) => row.id === sid
                            ? {
                                ...row,
                                messages: preferred,
                                messageCount: Math.max(row.messageCount ?? 0, preferred.length),
                            }
                            : row);
                    }
                }
                sessionsRef.current = nextSessions;
                setSessions(nextSessions);
            }
            catch {
                /* keep last good snapshot */
            }
            finally {
                inflight = false;
            }
        };
        void tick();
        const id = window.setInterval(() => void tick(), 2000);
        const onVis = () => {
            if (!document.hidden)
                void tick();
        };
        document.addEventListener("visibilitychange", onVis);
        return () => {
            cancelled = true;
            window.clearInterval(id);
            document.removeEventListener("visibilitychange", onVis);
        };
    }, [isProjectChat, projectId, chatsHydrated]);
    const loadMoreSessions = useCallback(async () => {
        if (!inSearchMode || sessionsLoadingMore || sessions.length >= sessionsTotal)
            return;
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
        }
        finally {
            setSessionsLoadingMore(false);
        }
    }, [inSearchMode, sessions.length, sessionsLoadingMore, sessionsTotal, serverSearchQuery]);
    const loadMidDaysChats = useCallback(async (opts) => {
        const append = !!opts?.append;
        if (append) {
            if (midDaysLoadingMore || midDaysLoadedCount >= midDaysTotal)
                return;
            setMidDaysLoadingMore(true);
        }
        else {
            if (midDaysLoading)
                return;
            setMidDaysLoading(true);
        }
        try {
            const remote = await fetchUserChatsFromServer({
                limit: 40,
                min_activity_ms: sidebarOlderThan7DaysCutoffMs(),
                max_activity_ms: sidebarOlderThan3DaysCutoffMs(),
                offset: append ? midDaysLoadedCount : 0,
                retainKnownSessionIds: true,
            });
            setSessions((prev) => {
                const merged = mergeRemoteChatSessions(prev, remote.sessions);
                sessionsRef.current = merged;
                return merged;
            });
            const page = remote.fetchedCount ?? remote.sessions.length;
            setMidDaysLoadedCount(append ? midDaysLoadedCount + page : page);
            setMidDaysTotal(remote.total ?? midDaysTotal);
        }
        finally {
            if (append)
                setMidDaysLoadingMore(false);
            else
                setMidDaysLoading(false);
        }
    }, [midDaysLoadedCount, midDaysLoading, midDaysLoadingMore, midDaysTotal]);
    const loadOlderChats = useCallback(async (opts) => {
        const append = !!opts?.append;
        if (append) {
            if (olderLoadingMore || olderLoadedCount >= olderTotal)
                return;
            setOlderLoadingMore(true);
        }
        else {
            if (olderLoading)
                return;
            setOlderLoading(true);
        }
        try {
            const remote = await fetchUserChatsFromServer({
                limit: 40,
                max_activity_ms: sidebarOlderThan7DaysCutoffMs(),
                offset: append ? olderLoadedCount : 0,
                retainKnownSessionIds: true,
            });
            setSessions((prev) => {
                const merged = mergeRemoteChatSessions(prev, remote.sessions);
                sessionsRef.current = merged;
                return merged;
            });
            const page = remote.fetchedCount ?? remote.sessions.length;
            setOlderLoadedCount(append ? olderLoadedCount + page : page);
            setOlderTotal(remote.total ?? olderTotal);
        }
        finally {
            if (append)
                setOlderLoadingMore(false);
            else
                setOlderLoading(false);
        }
    }, [olderLoadedCount, olderLoading, olderLoadingMore, olderTotal]);
    const toggleMidDaysSection = useCallback(() => {
        if (midDaysExpanded) {
            setMidDaysExpanded(false);
            return;
        }
        setMidDaysExpanded(true);
        if (midDaysLoadedCount === 0 && midDaysTotal > 0) {
            void loadMidDaysChats();
        }
    }, [midDaysExpanded, midDaysLoadedCount, midDaysTotal, loadMidDaysChats]);
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
        if (!el)
            return;
        const markUserScroll = () => {
            userScrolledRef.current = true;
        };
        const onScroll = () => {
            const userInitiated = userScrolledRef.current;
            userScrolledRef.current = false;
            pinScrollToBottomRef.current = pinAfterScrollEvent(pinScrollToBottomRef.current, userInitiated, scrollPinFromViewport(el));
            setShowScrollToBottomBtn(chatScrollJumpButtonVisible(el));
            if (el.scrollTop <= 4 && messagesHasOlder && !messagesLoadingOlder && activeIdRef.current) {
                const sid = activeIdRef.current;
                const session = sessionsRef.current.find((s) => s.id === sid);
                if (!session)
                    return;
                setMessagesLoadingOlder(true);
                void loadOlderSessionMessages(session)
                    .then(({ session: nextSession, hasMore }) => {
                    setMessagesHasOlder(hasMore);
                    setSessions((prev) => {
                        const updated = prev.map((s) => (s.id === sid ? nextSession : s));
                        sessionsRef.current = updated;
                        return updated;
                    });
                    if (sid === activeIdRef.current)
                        setMessages(nextSession.messages);
                })
                    .finally(() => setMessagesLoadingOlder(false));
            }
        };
        syncScrollPinFromContainer();
        el.addEventListener("scroll", onScroll, { passive: true });
        el.addEventListener("wheel", markUserScroll, { passive: true });
        el.addEventListener("touchmove", markUserScroll, { passive: true });
        const onMouseDown = (event) => {
            if (event.offsetX >= el.clientWidth)
                markUserScroll();
        };
        el.addEventListener("mousedown", onMouseDown);
        return () => {
            el.removeEventListener("scroll", onScroll);
            el.removeEventListener("wheel", markUserScroll);
            el.removeEventListener("touchmove", markUserScroll);
            el.removeEventListener("mousedown", onMouseDown);
        };
    }, [messagesHasOlder, messagesLoadingOlder, persistSessions, syncScrollPinFromContainer]);
    useEffect(() => {
        const onBackgroundMediaUpdate = (sessionId) => {
            if (isBackgroundImageRunning(sessionId) || isBackgroundVideoRunning(sessionId) || isBackgroundSpeechRunning(sessionId)) {
                setSessionStreaming(sessionId, true);
                return;
            }
            if (!sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId))) {
                setSessionStreaming(sessionId, false);
            }
            else {
                queueMicrotask(() => tryDrainPromptQueueRef.current(sessionId));
            }
            const session = sessionsRef.current.find((s) => s.id === sessionId);
            if (session?.privateMode)
                return;
            if (!abortControllersRef.current[sessionId]) {
                void fetchSessionWithMessages(sessionId)
                    .then((remote) => {
                    if (!remote?.messages.length)
                        return;
                    const local = sessionId === activeIdRef.current
                        ? messagesRef.current
                        : sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
                    const merged = mergeChatMessagesPreferLocal(local, remote.messages);
                    persistSessions((prev) => prev.map((s) => s.id === sessionId
                        ? {
                            ...s,
                            messages: merged,
                            revision: remote.revision ?? s.revision,
                            messageCount: Math.max(s.messageCount ?? 0, merged.length),
                        }
                        : s), { debounce: false });
                    if (sessionId === activeIdRef.current) {
                        setMessages(merged);
                    }
                    if (!sessionHasInFlightGeneration(merged)) {
                        setSessionStreaming(sessionId, false);
                    }
                })
                    .catch(() => { });
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
        const hasNonPrivatePending = sessions.some((s) => (sessionHasPendingImage(s.messages) ||
            messagesHavePendingVideo(s.messages) ||
            messagesHavePendingSpeech(s.messages)) &&
            !s.privateMode);
        if (!hasNonPrivatePending)
            return;
        const id = window.setInterval(() => {
            const sid = activeIdRef.current;
            if (!sid)
                return;
            const session = sessionsRef.current.find((s) => s.id === sid);
            if (session?.privateMode)
                return;
            void syncSessionsFromServer(sid);
        }, 5000);
        return () => window.clearInterval(id);
    }, [sessions, syncSessionsFromServer]);
    useEffect(() => {
        const sid = activeId;
        if (!sid || readOnly)
            return;
        const session = sessionsRef.current.find((s) => s.id === sid);
        if (!session || session.privateMode)
            return;
        const msgs = messagesRef.current.length ? messagesRef.current : session.messages;
        if (!sessionHasInFlightGeneration(msgs)) {
            if (streamingSessionsRef.current[sid] &&
                !isBackgroundImageRunning(sid) &&
                !isBackgroundVideoRunning(sid) &&
                !isBackgroundSpeechRunning(sid)) {
                setSessionStreaming(sid, false);
            }
            return;
        }
        if (isLocalWorkInFlight(sid))
            return;
        if (!isChatSessionOnServer(sid))
            return;
        setSessionStreaming(sid, true);
        let cancelled = false;
        const poll = () => {
            if (cancelled || activeIdRef.current !== sid)
                return;
            if (isLocalWorkInFlight(sid))
                return;
            void pollSessionMessagesFromServer(sid, { limit: 50 })
                .then(({ messages: remoteMsgs, revision }) => {
                if (cancelled || activeIdRef.current !== sid)
                    return;
                if (isLocalWorkInFlight(sid))
                    return;
                const mergedMsgs = preferLocalMessagesOverRemote(sid, remoteMsgs);
                setSessions((prev) => {
                    const next = prev.map((s) => s.id === sid
                        ? {
                            ...s,
                            messages: mergedMsgs,
                            revision,
                            messageCount: Math.max(s.messageCount ?? 0, mergedMsgs.length),
                        }
                        : s);
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
                if (cancelled || activeIdRef.current !== sid)
                    return;
                const localMsgs = activeIdRef.current === sid
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
        if (readOnly)
            return;
        const queuedSessionIds = Object.entries(promptQueues)
            .filter(([, items]) => items.length > 0)
            .map(([id]) => id);
        if (!queuedSessionIds.length)
            return;
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
        if (hydrateOutcome !== "empty" || !chatsHydrated || activeId || readOnly)
            return;
        if (!userPrefsReady || !models.length)
            return;
        const m = resolveNewChatModel(models, undefined, defaultModel);
        if (!m)
            return;
        const freshTools = copyFreshChatTools();
        const s = createSession(m, "New chat", freshTools);
        persistSessions((prev) => [s, ...prev], { debounce: false, metadataSessionIds: [s.id] });
        activeIdRef.current = s.id;
        setActiveId(s.id);
        setModel(s.model);
        setMessages([]);
        setChatTools(freshTools);
        seedProjectComposerCache(s, freshTools);
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
            syncComposerDraft(prev, composerInputRef.current, composerDirectionRef.current, pendingAttachmentsRef.current);
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
        }
        else {
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
            syncComposerDraft(activeIdRef.current, composerInputRef.current, composerDirectionRef.current, pendingAttachmentsRef.current);
        };
    }, []);
    useEffect(() => {
        if (restoringComposerRef.current || !activeId)
            return;
        syncComposerDraft(activeId, input, inputDirection, pendingAttachments);
    }, [activeId, input, inputDirection, pendingAttachments]);
    useEffect(() => {
        if (!activeId) {
            lastSyncedActiveIdRef.current = null;
            return;
        }
        const s = sessions.find((x) => x.id === activeId);
        if (!s)
            return;
        const switched = lastSyncedActiveIdRef.current !== activeId;
        lastSyncedActiveIdRef.current = activeId;
        if (!switched)
            return;
        pinScrollToBottomRef.current = true;
        setShowScrollToBottomBtn(false);
        applyComposerFromSession(s);
        requestAnimationFrame(() => {
            scrollChatToBottom("auto");
            syncScrollPinFromContainer();
        });
        if (!s.privateMode && !s.messages.length && (s.messageCount ?? 0) > 0) {
            void loadSessionMessagesIfNeeded(s, { limit: 50 }).then((loaded) => {
                if (activeIdRef.current !== activeId)
                    return;
                setMessages(loaded.messages);
                setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
                if (sessionHasIncompleteTextReply(loaded.messages)) {
                    setSessionStreaming(activeId, true);
                }
                else if (sessionHasPendingImage(loaded.messages)) {
                    setSessionStreaming(activeId, true);
                }
                applyLoadedSessionMessages(activeId, loaded);
            });
        }
        else {
            setMessages(s.messages);
            setMessagesHasOlder(false);
        }
    }, [activeId, sessions, scrollChatToBottom, applyLoadedSessionMessages, syncScrollPinFromContainer]);
    useLayoutEffect(() => {
        if (pinScrollToBottomRef.current) {
            scrollChatToBottom("auto");
            setShowScrollToBottomBtn(false);
            return;
        }
        const el = messagesScrollRef.current;
        if (!el)
            return;
        setShowScrollToBottomBtn(chatScrollJumpButtonVisible(el));
    }, [messages, activeId, isSessionStreaming, scrollChatToBottom]);
    useEffect(() => {
        const el = messagesScrollRef.current;
        const inner = messagesInnerRef.current;
        if (!el)
            return;
        const stickIfPinned = () => {
            if (!pinScrollToBottomRef.current) {
                setShowScrollToBottomBtn(chatScrollJumpButtonVisible(el));
                return;
            }
            scrollContainerToBottom(el, "auto");
            setShowScrollToBottomBtn(false);
        };
        const observer = new ResizeObserver(stickIfPinned);
        if (inner)
            observer.observe(inner);
        else
            observer.observe(el);
        el.addEventListener("load", stickIfPinned, true);
        el.addEventListener("loadeddata", stickIfPinned, true);
        return () => {
            observer.disconnect();
            el.removeEventListener("load", stickIfPinned, true);
            el.removeEventListener("loadeddata", stickIfPinned, true);
        };
    }, [messages, activeId]);
    useEffect(() => {
        return () => cancelStreamingMessagesFlush();
    }, [cancelStreamingMessagesFlush]);
    useEffect(() => {
        return () => {
            if (serverSaveTimerRef.current)
                window.clearTimeout(serverSaveTimerRef.current);
        };
    }, []);
    useEffect(() => {
        const el = textareaRef.current;
        if (!el)
            return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }, [input]);
    useEffect(() => {
        if (!toolsMenuOpen)
            return;
        const onDoc = (e) => {
            const target = e.target;
            if (toolsMenuRef.current?.contains(target))
                return;
            if (target instanceof Element && target.closest(".alpha-router-server-tools-menu"))
                return;
            setToolsMenuOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [toolsMenuOpen]);
    useEffect(() => {
        if (!agentMenuOpen)
            return;
        const onDoc = (e) => {
            const target = e.target;
            if (agentMenuRef.current?.contains(target))
                return;
            if (target instanceof Element && target.closest(".alpha-router-agent-menu"))
                return;
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
    const selectionSessionRef = useRef(null);
    useEffect(() => {
        if (selectionSessionRef.current === activeId)
            return;
        selectionSessionRef.current = activeId;
        setSelectedModelIds(model ? [model] : []);
    }, [activeId, model]);
    // If primary model is healed/changed without going through the picker, keep
    // it in the selection (as first) without dropping other selected models.
    useEffect(() => {
        if (!activeId || selectionSessionRef.current !== activeId)
            return;
        if (!model) {
            setSelectedModelIds([]);
            return;
        }
        setSelectedModelIds((prev) => {
            if (prev.length === 0)
                return [model];
            if (prev[0] === model)
                return prev;
            if (prev.includes(model))
                return [model, ...prev.filter((id) => id !== model)];
            return [model];
        });
    }, [model, activeId]);
    useEffect(() => {
        const onKey = (e) => {
            const mod = e.metaKey || e.ctrlKey;
            if (!mod)
                return;
            if (e.key.toLowerCase() === "k") {
                e.preventDefault();
                setToolsMenuOpen(false);
                setModelPickerMode("replace");
            }
            else if (e.key.toLowerCase() === "j") {
                e.preventDefault();
                setToolsMenuOpen(false);
                setModelPickerMode("append");
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);
    useEffect(() => {
        const mediaToolsOn = Boolean(chatTools.imageGeneration || chatTools.videoGeneration || chatTools.speechGeneration);
        const addModelDisabled = !models.length ||
            (!mediaToolsOn && selectedModelIds.length >= MAX_MULTI_MODELS);
        const addModelTitle = chatTools.speechGeneration
            ? "Text to Speech uses one model — picking another replaces it"
            : chatTools.videoGeneration
                ? "Video Generation uses one model — picking another replaces it"
                : chatTools.imageGeneration
                    ? "Image Generation uses one model — picking another replaces it"
                    : selectedModelIds.length >= MAX_MULTI_MODELS
                        ? `Maximum ${MAX_MULTI_MODELS} models`
                        : "Add model";
        const addModelAriaLabel = chatTools.speechGeneration
            ? "Change speech model"
            : chatTools.videoGeneration
                ? "Change video model"
                : chatTools.imageGeneration
                    ? "Change image model"
                    : "Add model for multi-model response";
        if (!enableModelChrome) {
            registerModelChrome(null);
            return () => registerModelChrome(null);
        }
        registerModelChrome({
            openReplacePicker: () => {
                setToolsMenuOpen(false);
                setModelPickerMode("replace");
            },
            openAppendPicker: () => {
                setToolsMenuOpen(false);
                setModelPickerMode("append");
            },
            modelsReady: models.length > 0,
            addModelDisabled,
            addModelTitle,
            addModelAriaLabel,
            selectedModels: selectedModels.map((m) => ({
                id: m.id,
                name: m.name,
                external_id: m.external_id,
            })),
            onRemoveModel: removeSelectedModel,
        });
        return () => registerModelChrome(null);
    }, [
        registerModelChrome,
        models.length,
        selectedModels,
        selectedModelIds.length,
        chatTools.imageGeneration,
        chatTools.videoGeneration,
        chatTools.speechGeneration,
        enableModelChrome,
    ]);
    async function apiMessages(history, forModel) {
        const trimmed = historyForModelRequest(history);
        const out = [];
        for (const m of trimmed) {
            const content = await buildApiMessageContentAsync(m.content, forModel);
            out.push({ role: m.role, content });
        }
        return out.filter((m) => hasApiContent(m.content));
    }
    async function chatCompletionBody(modelId, history, forModel, tools = chatTools, persist, privateMode = false) {
        const toolsPayload = toolsToApiPayload(tools);
        const includeUser = persist?.includeUserMessage !== false && persist?.userMessage;
        const sessionId = persist?.sessionId || activeIdRef.current;
        const agentFields = !privateMode && sessionId
            ? agentRequestFields(agentSelectionForSession(sessionId))
            : {};
        return {
            model: modelId,
            messages: await apiMessages(history, forModel),
            stream: true,
            private_mode: !!(privateMode && !isProjectChat),
            ...(isProjectChat && projectId ? { project_id: projectId } : {}),
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
    function ensureActiveSession() {
        if (activeIdRef.current)
            return activeIdRef.current;
        if (readOnly)
            return null;
        const m = resolveNewChatModel(models, model, defaultModel);
        if (!m)
            return null;
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
        seedProjectComposerCache(s, freshTools);
        return s.id;
    }
    function persistActiveComposerDraft(overrides) {
        const sid = activeIdRef.current;
        if (!sid)
            return;
        syncComposerDraft(sid, overrides?.text ?? composerInputRef.current, overrides?.direction ?? composerDirectionRef.current, overrides?.attachments ?? pendingAttachmentsRef.current);
    }
    function activateSessionFromRef(id) {
        const s = sessionsRef.current.find((x) => x.id === id);
        if (!s)
            return;
        activeIdRef.current = id;
        pinScrollToBottomRef.current = true;
        setActiveId(id);
        applyComposerFromSession(s);
        setChatError("");
        if (!s.privateMode && !s.messages.length && (s.messageCount ?? 0) > 0) {
            void loadSessionMessagesIfNeeded(s, { limit: 50 }).then((loaded) => {
                if (activeIdRef.current !== id)
                    return;
                setMessages(loaded.messages);
                setMessagesHasOlder((loaded.messageCount ?? 0) > loaded.messages.length);
                applyLoadedSessionMessages(id, loaded);
            });
        }
        else {
            setMessages(s.messages);
            setMessagesHasOlder(false);
        }
        requestAnimationFrame(() => scrollChatToBottom("auto"));
    }
    function syncProjectSessionQuery(id) {
        if (!isProjectChat)
            return;
        const params = new URLSearchParams(location.search);
        if (params.get("session") === id)
            return;
        params.set("session", id);
        navigate({ pathname: location.pathname, search: `?${params.toString()}` }, { replace: true });
    }
    function selectSession(id) {
        onProjectChatFocus?.();
        activateSessionFromRef(id);
        syncProjectSessionQuery(id);
    }
    async function togglePinSession(session) {
        if (!projectId)
            return;
        try {
            if (session.pinned)
                await unpinProjectChat(projectId, session.id);
            else
                await pinProjectChat(projectId, session.id);
            persistSessions((prev) => {
                const next = prev.map((row) => row.id === session.id ? { ...row, pinned: !session.pinned } : row);
                return sortProjectSessions(next);
            });
        }
        catch (err) {
            setChatError(err instanceof Error ? err.message : "Could not update pin.");
        }
    }
    async function copyProjectChatLink(sessionId) {
        const url = `${window.location.origin}${location.pathname}?session=${encodeURIComponent(sessionId)}`;
        try {
            await navigator.clipboard.writeText(url);
        }
        catch {
            setChatError("Could not copy chat link.");
        }
    }
    useEffect(() => {
        function onReplyReadyFocus(ev) {
            const detail = ev.detail;
            const sid = typeof detail?.sessionId === "string" ? detail.sessionId.trim() : "";
            if (!sid)
                return;
            activateSessionFromRef(sid);
        }
        window.addEventListener(REPLY_READY_FOCUS_EVENT, onReplyReadyFocus);
        return () => window.removeEventListener(REPLY_READY_FOCUS_EVENT, onReplyReadyFocus);
    }, []);
    useEffect(() => {
        if (!isProjectChat || !chatsHydrated || !projectId)
            return;
        const wanted = new URLSearchParams(location.search).get("session");
        if (!wanted || wanted === activeIdRef.current)
            return;
        if (sessionsRef.current.some((row) => row.id === wanted)) {
            activateSessionFromRef(wanted);
            return;
        }
        let cancelled = false;
        void fetchProjectChatById(projectId, wanted).then((fetched) => {
            if (cancelled || !fetched)
                return;
            persistSessions((prev) => sortProjectSessions([fetched, ...prev.filter((row) => row.id !== fetched.id)]), { debounce: false, metadataSessionIds: [fetched.id] });
            activateSessionFromRef(wanted);
        });
        return () => {
            cancelled = true;
        };
    }, [chatsHydrated, isProjectChat, location.search, persistSessions, projectId]);
    function isSuccessfulNotifyContent(content) {
        const text = (content || "").trim();
        if (!text)
            return false;
        if (text === IMAGE_PENDING_MARKER ||
            text === VIDEO_PENDING_MARKER ||
            text === SPEECH_PENDING_MARKER) {
            return false;
        }
        if (text.startsWith("Error:") || text.startsWith("No response from model."))
            return false;
        if (text === "Image generation stopped." ||
            text === "Speech generation stopped." ||
            text.startsWith("Image generation timed out") ||
            text.startsWith("Speech generation timed out") ||
            text.startsWith("Preparing the")) {
            return false;
        }
        return true;
    }
    function maybeNotifyReplyReady(sessionId, messageKey, content) {
        if (readOnly)
            return;
        if (!replyNotifyPrefsRef.current.away)
            return;
        if (!isSuccessfulNotifyContent(content))
            return;
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
    function maybeNotifyMediaReady(sessionId, messageKey, allowRetry = true) {
        const fromActive = sessionId === activeIdRef.current ? messagesRef.current : undefined;
        const fromSession = sessionsRef.current.find((s) => s.id === sessionId)?.messages;
        const msgs = fromActive?.length ? fromActive : fromSession?.length ? fromSession : getSessionMessages(sessionId);
        let lastAssistant;
        for (let i = msgs.length - 1; i >= 0; i -= 1) {
            if (msgs[i].role === "assistant") {
                lastAssistant = msgs[i];
                break;
            }
        }
        if (!lastAssistant)
            return;
        const content = lastAssistant.content || "";
        const stillPending = content === IMAGE_PENDING_MARKER ||
            content === VIDEO_PENDING_MARKER ||
            content === SPEECH_PENDING_MARKER;
        if (stillPending) {
            // Image/speech sync may land in sessionsRef a tick after the job resolves.
            if (allowRetry) {
                window.setTimeout(() => maybeNotifyMediaReady(sessionId, messageKey, false), 400);
            }
            return;
        }
        const mediaOk = content.startsWith(IMAGE_MESSAGE_PREFIX) ||
            content.startsWith(VIDEO_MESSAGE_PREFIX) ||
            content.startsWith(SPEECH_MESSAGE_PREFIX);
        if (!mediaOk)
            return;
        const key = (messageKey || "").trim() ||
            lastAssistant.clientMessageId ||
            lastAssistant.id ||
            `${sessionId}:media:${lastAssistant.receivedAt ?? Date.now()}`;
        maybeNotifyReplyReady(sessionId, key, content);
    }
    function startNewChat() {
        if (readOnly)
            return;
        onProjectChatFocus?.();
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
        seedProjectComposerCache(s, freshTools);
        clearChatSelection();
        setToolsMenuOpen(false);
        setChatError("");
        requestAnimationFrame(() => scrollChatToBottom("auto"));
    }
    async function removeChatSession(id) {
        stopBackgroundImageGeneration(id);
        stopBackgroundVideoGeneration(id);
        clearComposerDraft(id);
        setSelectedChatIds((prev) => {
            if (!prev.has(id))
                return prev;
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
            void cancelStreamingReplyOnServer(id).catch(() => { });
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
                }
                else if (models.length) {
                    const s = createSession(resolveNewChatModel(models, undefined, defaultModel));
                    queueMicrotask(() => {
                        setActiveId(s.id);
                        setModel(s.model);
                        setMessages([]);
                        setChatTools(copyFreshChatTools());
                    });
                    return [s];
                }
                else {
                    setActiveId(null);
                    setMessages([]);
                }
            }
            return next;
        });
        if (sessionPrivateMode(id))
            return;
        try {
            await deleteChatSessionOnServer(id);
        }
        catch (err) {
            if (deletedSession) {
                persistSessions((prev) => {
                    if (prev.some((s) => s.id === id))
                        return prev;
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
    async function deleteSession(id, e) {
        e?.stopPropagation();
        if (readOnly)
            return;
        await removeChatSession(id);
    }
    function startRenameSession(session, e) {
        e?.stopPropagation();
        if (readOnly)
            return;
        setRenamingSessionId(session.id);
        setRenamingTitle(session.title || "");
    }
    function commitRenameSession() {
        const sid = renamingSessionId;
        if (!sid)
            return;
        const title = renamingTitle.trim();
        if (!title) {
            setRenamingSessionId(null);
            setRenamingTitle("");
            return;
        }
        persistSessions((prev) => prev.map((s) => s.id === sid
            ? {
                ...s,
                title,
                titleLocked: true,
                updatedAt: Date.now(),
            }
            : s), { debounce: false, metadataSessionIds: [sid] });
        if (!sessionPrivateMode(sid)) {
            void pushSessionMetadataToServer(sid).catch(() => { });
        }
        setRenamingSessionId(null);
        setRenamingTitle("");
    }
    function addFolder() {
        if (readOnly)
            return;
        const name = newFolderName.trim();
        if (!name)
            return;
        const f = createFolder(name);
        persistFolders((prev) => [f, ...prev]);
        setCollapsedFolders((prev) => ({ ...prev, [f.id]: false }));
        setNewFolderName("");
    }
    function toggleFolderCollapse(folderId) {
        setCollapsedFolders((prev) => ({ ...prev, [folderId]: !prev[folderId] }));
    }
    function startRenameFolder(folder, e) {
        e?.stopPropagation();
        setRenamingFolderId(folder.id);
        setRenamingFolderName(folder.name || "");
    }
    function commitRenameFolder() {
        const fid = renamingFolderId;
        if (!fid)
            return;
        const name = renamingFolderName.trim();
        if (!name) {
            setRenamingFolderId(null);
            setRenamingFolderName("");
            return;
        }
        persistFolders((prev) => prev.map((f) => (f.id === fid ? { ...f, name, updatedAt: Date.now() } : f)));
        setRenamingFolderId(null);
        setRenamingFolderName("");
    }
    function cleanupFolderState(folderId) {
        setCollapsedFolders((prev) => {
            if (!(folderId in prev))
                return prev;
            const next = { ...prev };
            delete next[folderId];
            return next;
        });
        if (dropFolderId === folderId)
            setDropFolderId(null);
        if (renamingFolderId === folderId) {
            setRenamingFolderId(null);
            setRenamingFolderName("");
        }
    }
    function removeFolderRecord(folderId) {
        persistFolders((prev) => prev.filter((f) => f.id !== folderId));
        cleanupFolderState(folderId);
    }
    function deleteFolderKeepChats(folderId) {
        const affectedIds = sessionsRef.current
            .filter((s) => s.folderId === folderId)
            .map((s) => s.id);
        removeFolderRecord(folderId);
        persistSessions((prev) => prev.map((s) => (s.folderId === folderId ? { ...s, folderId: null } : s)), { debounce: false, metadataSessionIds: affectedIds });
        for (const id of affectedIds) {
            if (!sessionPrivateMode(id)) {
                void pushSessionMetadataToServer(id).catch(() => { });
            }
        }
    }
    function deleteFolderAndChats(folderId, chatsInFolder) {
        const removedIds = new Set(chatsInFolder.map((c) => c.id));
        removedIds.forEach((sessionId) => clearComposerDraft(sessionId));
        removeFolderRecord(folderId);
        persistSessions((prev) => {
            let next = prev.filter((s) => !removedIds.has(s.id));
            if (activeId && removedIds.has(activeId)) {
                if (next.length) {
                    queueMicrotask(() => selectSession(next[0].id));
                }
                else if (models.length) {
                    const s = createSession(resolveNewChatModel(models, undefined, defaultModel));
                    next = [s, ...next];
                    queueMicrotask(() => {
                        activeIdRef.current = s.id;
                        setActiveId(s.id);
                        setModel(s.model);
                        setMessages([]);
                        setChatTools(copyFreshChatTools());
                    });
                }
                else {
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
    async function confirmDeleteFolder(folder) {
        const chatsInFolder = sessions.filter((s) => s.folderId === folder.id);
        const proceed = await confirm({
            title: "Delete folder",
            message: chatsInFolder.length > 0
                ? `Delete folder "${folder.name}"? It contains ${chatsInFolder.length} chat(s).`
                : `Delete folder "${folder.name}"?`,
            confirmLabel: chatsInFolder.length > 0 ? "Continue" : "Delete",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!proceed)
            return;
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
        if (choice === false)
            return;
        if (choice === "secondary") {
            deleteFolderKeepChats(folder.id);
            return;
        }
        deleteFolderAndChats(folder.id, chatsInFolder);
    }
    function setFolderColor(folderId, color) {
        persistFolders((prev) => prev.map((f) => (f.id === folderId ? { ...f, color: color || null, updatedAt: Date.now() } : f)));
    }
    function moveSessionToFolder(sessionId, folderId) {
        persistSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, folderId } : s)), { debounce: false, metadataSessionIds: [sessionId] });
        if (!sessionPrivateMode(sessionId)) {
            void pushSessionMetadataToServer(sessionId).catch(() => { });
        }
        setDropFolderId(null);
    }
    function moveSessionsToFolder(sessionIds, folderId) {
        if (!sessionIds.length)
            return;
        const idSet = new Set(sessionIds);
        persistSessions((prev) => prev.map((s) => (idSet.has(s.id) ? { ...s, folderId } : s)), { debounce: false, metadataSessionIds: sessionIds });
        for (const sessionId of sessionIds) {
            if (!sessionPrivateMode(sessionId)) {
                void pushSessionMetadataToServer(sessionId).catch(() => { });
            }
        }
        setDropFolderId(null);
        setSelectedChatIds(new Set());
    }
    function toggleChatSelected(sessionId) {
        setSelectedChatIds((prev) => {
            const next = new Set(prev);
            if (next.has(sessionId))
                next.delete(sessionId);
            else
                next.add(sessionId);
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
        if (readOnly)
            return;
        const ids = [...selectedChatIds];
        if (!ids.length)
            return;
        const ok = await confirm({
            title: "Delete chats",
            message: `Delete ${ids.length} chat${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
            confirmLabel: "Delete",
            danger: true,
        });
        if (!ok)
            return;
        const active = activeIdRef.current;
        const ordered = active && ids.includes(active) ? [...ids.filter((id) => id !== active), active] : ids;
        clearChatSelection();
        for (const id of ordered) {
            await removeChatSession(id);
        }
    }
    function sessionDisplayTitle(s) {
        if (!isDefaultChatTitle(s.title))
            return s.title;
        const derived = sessionTitleFromMessages(s.messages);
        return !isDefaultChatTitle(derived) ? derived : s.title || DEFAULT_CHAT_TITLE;
    }
    function renderSessionRow(s, wrap = "li") {
        const isRenaming = renamingSessionId === s.id;
        const isSelected = selectedChatIds.has(s.id);
        const selectionActive = selectedChatIds.size > 0;
        const inner = (_jsxs(_Fragment, { children: [!readOnly && !isRenaming ? (_jsx("label", { className: `alpha-router-history-check${isSelected || selectionActive ? " is-visible" : ""}`, title: "Select chat", onMouseDown: (e) => e.stopPropagation(), onClick: (e) => e.stopPropagation(), children: _jsx("input", { type: "checkbox", checked: isSelected, onChange: () => toggleChatSelected(s.id), "aria-label": `Select ${sessionDisplayTitle(s)}` }) })) : null, isRenaming ? (_jsx("form", { className: "alpha-router-history-rename", onSubmit: (e) => {
                        e.preventDefault();
                        commitRenameSession();
                    }, children: _jsx("input", { value: renamingTitle, onChange: (e) => setRenamingTitle(e.target.value), onBlur: commitRenameSession, autoFocus: true }) })) : (_jsxs("button", { type: "button", className: `alpha-router-history-item${s.id === activeId ? " active" : ""}${isSelected ? " is-selected" : ""}${streamingSessions[s.id] || isBackgroundImageRunning(s.id) || isBackgroundVideoRunning(s.id) || isBackgroundSpeechRunning(s.id) ? " is-streaming" : ""}`, onClick: () => selectSession(s.id), children: [s.privateMode ? (_jsx("span", { className: "alpha-router-history-item__lock", title: "Private Mode", "aria-hidden": true, children: _jsx(PrivateModeLockIcon, { className: "alpha-router-history-item__lock-icon", size: 14 }) })) : null, s.pinned ? (_jsx("span", { className: "alpha-router-history-item__pin", title: "Pinned", "aria-hidden": true, children: _jsx("svg", { viewBox: "0 0 24 24", width: "12", height: "12", fill: "currentColor", children: _jsx("path", { d: "M14.5 3.5 20.5 9.5 13 17l-1.5-1.5L9 18l-3-3 2.5-2.5L7 11l7.5-7.5Z" }) }) })) : null, streamingSessions[s.id] || isBackgroundImageRunning(s.id) || isBackgroundVideoRunning(s.id) || isBackgroundSpeechRunning(s.id) ? (_jsx("span", { className: "alpha-router-history-item__busy", title: "Generating\u2026", "aria-hidden": true })) : null, sessionDisplayTitle(s)] })), !readOnly && !isRenaming ? (_jsxs("div", { className: "alpha-router-history-item-actions", onMouseDown: (e) => e.stopPropagation(), onClick: (e) => e.stopPropagation(), children: [_jsx("button", { type: "button", className: "alpha-router-history-delete", title: "Delete chat", "aria-label": `Delete ${sessionDisplayTitle(s)}`, onClick: (e) => void deleteSession(s.id, e), children: _jsx("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true", children: _jsx("path", { d: "M6 6l12 12M18 6L6 18", strokeLinecap: "round" }) }) }), _jsx(RowActionsMenu, { label: "\u22EF", menuClassName: "row-actions-menu--sidebar", actions: isProjectChat
                                ? [
                                    { label: "Rename", onClick: () => startRenameSession(s) },
                                    {
                                        label: s.pinned ? "Unpin" : "Pin",
                                        onClick: () => void togglePinSession(s),
                                    },
                                    {
                                        label: "Copy link",
                                        onClick: () => void copyProjectChatLink(s.id),
                                    },
                                    {
                                        label: "Delete",
                                        onClick: () => void deleteSession(s.id),
                                        danger: true,
                                    },
                                ]
                                : [
                                    { label: "Rename", onClick: () => startRenameSession(s) },
                                    { label: "Move", onClick: () => setMovingSessionIds([s.id]) },
                                    {
                                        label: "Delete",
                                        onClick: () => void deleteSession(s.id),
                                        danger: true,
                                    },
                                ] })] })) : null] }));
        const dragProps = {
            draggable: !readOnly,
            onDragStart: () => {
                if (readOnly)
                    return;
                setDraggingSessionId(s.id);
            },
            onDragEnd: () => {
                setDraggingSessionId(null);
                setDropFolderId(null);
            },
        };
        const rowClass = `alpha-router-history-row${isSelected ? " is-selected" : ""}`;
        if (wrap === "div") {
            return (_jsx("div", { className: rowClass, ...dragProps, children: inner }, s.id));
        }
        return (_jsx("li", { className: isSelected ? "is-selected" : undefined, ...dragProps, children: inner }, s.id));
    }
    function persistSessionPrimaryModel(id) {
        setChatError("");
        const sid = activeIdRef.current || ensureActiveSession();
        if (!sid)
            return;
        persistSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, model: id } : s)), { debounce: false, metadataSessionIds: isProjectChat ? [] : [sid] });
        if (isProjectChat) {
            scheduleComposerPrefSave(sid);
            return;
        }
        if (!sessionPrivateMode(sid)) {
            void pushSessionMetadataToServer(sid).catch(() => { });
        }
    }
    /** Search modal: replace entire multi-selection with one model. */
    function replaceModelSelection(id) {
        setModel(id);
        setSelectedModelIds([id]);
        setModelPickerMode(null);
        persistSessionPrimaryModel(id);
    }
    /** Add Model: append for multi-model UI (blocked while media generation is on). */
    function appendModelSelection(id) {
        if (chatToolsRef.current.imageGeneration ||
            chatToolsRef.current.videoGeneration ||
            chatToolsRef.current.speechGeneration) {
            // Media generation is single-model only — Add Model replaces the primary.
            replaceModelSelection(id);
            return;
        }
        setSelectedModelIds((prev) => {
            if (prev.includes(id))
                return prev;
            if (prev.length >= MAX_MULTI_MODELS)
                return prev;
            const next = prev.length === 0 ? [id] : [...prev, id];
            if (prev.length === 0) {
                setModel(id);
                persistSessionPrimaryModel(id);
            }
            return next;
        });
        setModelPickerMode(null);
    }
    function removeSelectedModel(id) {
        setSelectedModelIds((prev) => {
            const next = prev.filter((x) => x !== id);
            if (id === model) {
                const primary = next[0] || "";
                setModel(primary);
                if (primary)
                    persistSessionPrimaryModel(primary);
            }
            return next;
        });
    }
    function pickModel(id) {
        replaceModelSelection(id);
    }
    function resolveImageGenerationModel(candidate) {
        if (isAutoRouterModel(candidate))
            return candidate;
        // Resolve for the request only — do not collapse multi-selection via pickModel.
        return resolveConcreteImageModel(models, candidate);
    }
    function resolveVideoGenerationModel(candidate) {
        if (isAutoRouterModel(candidate))
            return candidate;
        // Resolve for the request only — do not collapse multi-selection via pickModel.
        return resolveConcreteVideoModel(models, candidate);
    }
    function resolveSpeechGenerationModel(candidate) {
        if (isAutoRouterModel(candidate))
            return candidate;
        return resolveConcreteSpeechModel(models, candidate);
    }
    function willRoutePromptToVideoGeneration(tools, primaryModel) {
        if (!tools.videoGeneration)
            return false;
        const turnModel = resolveVideoGenerationModel(primaryModel);
        return shouldRouteToVideoGeneration({
            videoGenerationEnabled: true,
            modelSupportsVideo: modelSupportsVideos(turnModel, models),
        });
    }
    function willRoutePromptToSpeechGeneration(tools, primaryModel) {
        if (!tools.speechGeneration)
            return false;
        const turnModel = resolveSpeechGenerationModel(primaryModel);
        return shouldRouteToSpeechGeneration({
            speechGenerationEnabled: true,
            modelSupportsSpeech: modelSupportsSpeech(turnModel, models),
        });
    }
    function willRoutePromptToImageGeneration(userContent, tools, primaryModel, priorMessages) {
        const turnModel = tools.imageGeneration
            ? resolveImageGenerationModel(primaryModel)
            : primaryModel;
        return shouldRouteToImageGeneration(userContent, tools.imageGeneration, modelSupportsTextToImage(turnModel, models), modelSupportsImageToImage(turnModel, models), lastAssistantImageUrl(priorMessages));
    }
    function setAsDefaultModel(id, e) {
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
    async function streamTextCompletion(modelId, history, forModel, signal, onPartial, tools = chatTools, persist, privateMode = false) {
        const res = await authFetch("/api/chat/completions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(await chatCompletionBody(modelId, history, forModel, tools, persist, privateMode)),
            signal,
        });
        if (!res.ok) {
            const parsed = parseApiError(await res.text(), res.status);
            const retryAfterHeader = Number(res.headers.get("Retry-After"));
            if (parsed.retryAfterSeconds == null
                && Number.isFinite(retryAfterHeader)
                && retryAfterHeader > 0) {
                parsed.retryAfterSeconds = Math.ceil(retryAfterHeader);
            }
            throw new ChatCompletionApiError(parsed, res.status);
        }
        const reader = res.body?.getReader();
        if (!reader)
            throw new Error("No response stream");
        const decoder = new TextDecoder();
        let assistant = "";
        let buffer = "";
        let requestLogId;
        let agentMetadata;
        while (true) {
            const { done, value } = await reader.read();
            if (done)
                break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
                if (!line.startsWith("data: "))
                    continue;
                const payload = line.slice(6).trim();
                if (payload === "[DONE]")
                    continue;
                try {
                    const json = JSON.parse(payload);
                    if (json.error) {
                        const errMsg = typeof json.error === "string"
                            ? json.error
                            : json.error?.message || JSON.stringify(json.error);
                        throw new Error(errMsg);
                    }
                    const metaLogId = json?.alpha_router?.request_log_id;
                    if (typeof metaLogId === "number" && Number.isFinite(metaLogId)) {
                        requestLogId = metaLogId;
                    }
                    const nextAgentMetadata = agentCompletionMetadataFromSse(json?.alpha_router);
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
                }
                catch (err) {
                    if (err instanceof SyntaxError)
                        continue;
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
    async function openMessageCostDetails(requestLogId) {
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
        }
        catch (err) {
            setCostDetailsError(err instanceof Error ? err.message : "Failed to load cost details");
        }
        finally {
            setCostDetailsLoading(false);
        }
    }
    function closeMessageCostDetails() {
        setCostDetailsLog(null);
        setCostDetails(null);
        setCostDetailsError("");
        setCostDetailsLoading(false);
    }
    function historyForCompletionApi(history) {
        const last = history.at(-1);
        if (last?.role === "assistant" && !(last.content || "").trim()) {
            return history.slice(0, -1);
        }
        return history;
    }
    /** API history for a multi-model turn: through the user message only (no sibling assistants). */
    function historyThroughUserMessage(messages, userMessage) {
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
        if (uidx < 0)
            return historyForModelRequest(historyForCompletionApi(messages));
        return historyForModelRequest(messages.slice(0, uidx + 1));
    }
    function resolveTurnModels(primary) {
        const ids = selectedModelIdsRef.current.length
            ? selectedModelIdsRef.current
            : [primary.id];
        const out = [];
        const seen = new Set();
        for (const id of ids) {
            const m = models.find((x) => x.id === id) || models.find((x) => x.external_id === id);
            if (!m || seen.has(m.id))
                continue;
            seen.add(m.id);
            out.push(m);
            if (out.length >= MAX_MULTI_MODELS)
                break;
        }
        return out.length ? out : [primary];
    }
    function isDedicatedMediaModel(m) {
        if (!m || isAutoRouterModel(m))
            return false;
        if (m.is_video_model || m.supports_text_to_video)
            return true;
        if (m.is_speech_model || m.supports_text_to_speech)
            return true;
        // Pure image generators often cannot run chat_title completions.
        if ((m.is_image_model || m.supports_text_to_image) && !m.supports_vision)
            return true;
        return false;
    }
    function resolveSessionTitleModelId(mediaModelId) {
        const preferred = resolveDefaultModelPreference(models, defaultModel) ||
            resolveDefaultModelPreference(models, models.find((m) => m.is_system_default)?.id);
        if (preferred) {
            const preferredModel = models.find((m) => m.id === preferred);
            if (preferredModel && !isDedicatedMediaModel(preferredModel))
                return preferred;
        }
        const auto = models.find(isAutoRouterModel);
        if (auto)
            return auto.id;
        const textModel = models.find((m) => !isDedicatedMediaModel(m));
        if (textModel)
            return textModel.id;
        return (mediaModelId || "").trim();
    }
    function friendlyTurnError(err) {
        if (err instanceof ChatCompletionApiError
            && err.code === "code_interpreter_capacity_busy") {
            const retry = err.retryAfterSeconds && err.retryAfterSeconds > 0
                ? ` Try again in about ${err.retryAfterSeconds} seconds.`
                : " Please try again later.";
            return `Code Interpreter is currently busy.${retry}`;
        }
        if (err instanceof ChatCompletionApiError
            && err.code === "code_interpreter_capacity_unavailable") {
            return "Code Interpreter is temporarily unavailable because capacity coordination is offline. Please try again shortly.";
        }
        if (err instanceof ChatCompletionApiError
            && err.code === "code_interpreter_workspace_limit") {
            return err.message;
        }
        const message = err instanceof Error ? err.message : String(err);
        if (message.includes("network") || message === "Failed to fetch") {
            return `Cannot reach ${PRODUCT_NAME} API. Check that Docker is running and hard-refresh (Ctrl+Shift+R).`;
        }
        return message;
    }
    async function syncTextTurnToServer(sessionId, turnMessages) {
        if (sessionPrivateMode(sessionId))
            return;
        // The backend ChatCompletionPersister owns the assistant row (append + stream
        // PATCH + finalize). Pushing a trailing empty assistant placeholder here would
        // race that writer and could blank out streamed content, so drop it.
        const tail = turnMessages.at(-1);
        const toSync = tail?.role === "assistant" && !(tail.content || "").trim()
            ? turnMessages.slice(0, -1)
            : turnMessages;
        if (!toSync.length)
            return;
        await syncSessionMessagesToServer(sessionId, toSync);
        patchDefaultTitleFromMessages(sessionId, toSync);
    }
    async function runChatTurn(sid, historyWithUser, primaryModel, controller, turnBaseCount, persistCtx, options) {
        const emptyReply = "No response from model. Check Connections and enable the model in Admin → Models.";
        const turnSession = sessionsRef.current.find((s) => s.id === sid);
        const specialistTurn = !sessionPrivateMode(sid)
            && agentSelectionForSession(sid) !== NO_AGENT_SELECTION;
        const turnTools = specialistTurn
            ? copyFreshChatTools()
            : sid === activeIdRef.current
                ? chatToolsRef.current
                : sessionTools(turnSession);
        const historyForApi = historyForCompletionApi(historyWithUser);
        const scopedHistory = historyForModelRequest(historyForApi);
        const userContent = scopedHistory.filter((m) => m.role === "user").at(-1)?.content || "";
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
            const pendingMsgs = [
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
            }
            catch (err) {
                if (err instanceof DOMException && err.name === "AbortError")
                    return;
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
            const pendingMsgs = [
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
            }
            catch (err) {
                if (err instanceof DOMException && err.name === "AbortError")
                    return;
                setChatError(friendlyTurnError(err));
                void scheduleSessionTitle(sid, titleModelId, getSessionMessages(sid));
            }
            return;
        }
        const usePriorImage = promptImpliesImageEdit(promptText);
        const priorImage = usePriorImage
            ? lastAssistantImageUrl(scopedHistory.slice(0, -1))
            : undefined;
        const referenceImage = await resolveImageGenerationReferenceAsync(userContent, scopedHistory.slice(0, -1), usePriorImage);
        const allowImageRoute = allowMediaRoute;
        const turnModel = allowImageRoute && turnTools.imageGeneration
            ? resolveImageGenerationModel(primaryModel)
            : primaryModel;
        if (allowImageRoute &&
            shouldRouteToImageGeneration(userContent, turnTools.imageGeneration, modelSupportsTextToImage(turnModel, models), modelSupportsImageToImage(turnModel, models), priorImage)) {
            if (referenceImage && !modelSupportsImageToImage(turnModel, models)) {
                const errAssistant = {
                    role: "assistant",
                    content: "Error: The selected model does not support image-to-image. Choose a model that accepts image input (e.g. Gemini image or FLUX Kontext).",
                    receivedAt: Date.now(),
                    clientMessageId: newClientMessageId(),
                    modelId: turnModel.id,
                    modelName: turnModel.name,
                };
                const base = historyForApi.at(-1)?.role === "assistant" && !(historyForApi.at(-1)?.content || "").trim()
                    ? historyForApi.slice(0, -1)
                    : historyForApi;
                const errMsgs = [...base, errAssistant];
                const userForPersist = persistCtx?.userMessage ?? base.filter((m) => m.role === "user").at(-1) ?? undefined;
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
            const pendingMsgs = [
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
                }
                else {
                    const session = await fetchSessionWithMessages(sid);
                    if (session) {
                        const local = sessionsRef.current.find((s) => s.id === sid);
                        const msgs = session.messages.length > 0
                            ? session.messages
                            : local?.messages.length
                                ? local.messages
                                : session.messages;
                        flushSync(() => updateSessionMessages(sid, msgs));
                        deferSessionTitle(sid, titleModelId, msgs);
                    }
                }
            }
            catch (err) {
                if (err instanceof DOMException && err.name === "AbortError")
                    return;
                setChatError(friendlyTurnError(err));
                const titleModelId = resolveSessionTitleModelId(turnModel.id);
                if (sessionPrivateMode(sid)) {
                    const local = sessionsRef.current.find((s) => s.id === sid);
                    if (local) {
                        void scheduleSessionTitle(sid, titleModelId, local.messages);
                    }
                }
                else {
                    const session = await fetchSessionWithMessages(sid);
                    if (session) {
                        const local = getLocalMessagesForSession(sid);
                        const msgs = mergeChatMessagesPreferLocal(local.length ? local : sessionsRef.current.find((s) => s.id === sid)?.messages ?? [], session.messages);
                        flushSync(() => updateSessionMessages(sid, msgs));
                        void scheduleSessionTitle(sid, titleModelId, msgs);
                    }
                }
            }
            return;
        }
        const assistantClientMessageId = persistCtx?.assistantClientMessageId ?? newClientMessageId();
        const userMsg = persistCtx?.userMessage ??
            historyForApi.filter((m) => m.role === "user").at(-1) ??
            historyWithUser.at(-1);
        const includeUserMessage = persistCtx?.includeUserMessage !== false;
        if (!persistCtx) {
            const placeholder = {
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
        const apiHistory = historyThroughUserMessage(liveForApi.length ? liveForApi : historyWithUser, userMsg);
        const patchAssistantInSession = (content, receivedAt, requestLogId, agentMetadata) => {
            const current = getSessionMessages(sid);
            const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
            const assistantMsg = {
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
        const streamed = await streamTextCompletion(primaryModel.id, apiHistory, primaryModel, controller.signal, (content) => {
            if (turnPhasesRef.current[sid] !== "writing") {
                setTurnPhase(sid, "writing");
            }
            applyMessagesStreaming(sid, patchAssistantInSession(content));
        }, turnTools, useServerPersist
            ? {
                sessionId: sid,
                userMessage: userMsg,
                assistantClientMessageId,
                includeUserMessage,
            }
            : undefined, sessionPrivateMode(sid));
        const receivedAt = Date.now();
        const finalContent = streamed.content.trim() ? streamed.content : emptyReply;
        const finalMsgs = patchAssistantInSession(finalContent, receivedAt, streamed.requestLogId, streamed.agentMetadata);
        applyMessages(sid, finalMsgs);
        applyAgentMetadataToSession(sid, streamed.agentMetadata);
        maybeNotifyReplyReady(sid, assistantClientMessageId, finalContent);
        if (useServerPersist && !options?.skipReconcile) {
            void fetchSessionWithMessages(sid).then((remote) => {
                if (!remote?.messages.length)
                    return;
                if (activeIdRef.current !== sid && !sessionsRef.current.some((s) => s.id === sid))
                    return;
                const local = getLocalMessagesForSession(sid);
                const reconciled = mergeChatMessagesPreferLocal(local, remote.messages, isLocalWorkInFlight(sid));
                applyMessages(sid, reconciled);
            });
        }
        if (streamed.agentMetadata?.agentRunId) {
            void fetchPendingAgentHandoffs(sid)
                .then((items) => {
                if (activeIdRef.current === sid)
                    setPendingHandoffs(items);
            })
                .catch(() => { });
        }
        patchDefaultTitleFromMessages(sid, finalMsgs);
        if (!options?.skipTitle) {
            void scheduleSessionTitle(sid, primaryModel.id, finalMsgs);
        }
    }
    async function togglePrivateMode(next) {
        if (isProjectChat)
            return;
        const sid = activeIdRef.current;
        if (!sid)
            return;
        if (next) {
            setToolsMenuOpen(false);
            const firstConfirmed = await confirm({
                title: "Enable Private Mode?",
                message: "Messages and media will be stored only in this browser. Private Mode cannot be turned off for this chat.",
                emphasize: "Private Mode cannot be turned off for this chat",
                confirmLabel: "Continue",
                cancelLabel: "Cancel",
            });
            if (!firstConfirmed)
                return;
            const finalConfirmed = await confirm({
                title: "Final confirmation",
                message: "This change is permanent. This chat will be deleted when you log out or clear browser data.",
                emphasize: "deleted",
                emphasizeDanger: true,
                confirmLabel: "Enable Permanently",
                cancelLabel: "Cancel",
                danger: true,
            });
            if (!finalConfirmed)
                return;
            persistSessions((prev) => prev.map((s) => s.id === sid ? { ...s, privateMode: true, updatedAt: Date.now() } : s), { debounce: false });
            return;
        }
        // Private Mode is intentionally irreversible for an existing chat.
        return;
    }
    function updateChatTools(next) {
        const prev = chatToolsRef.current;
        chatToolsRef.current = next;
        setChatTools(next);
        const sid = activeIdRef.current;
        if (sid) {
            persistSessions((prevSessions) => prevSessions.map((s) => s.id === sid ? { ...s, tools: { ...next }, toolsTouched: true, updatedAt: Date.now() } : s), { debounce: false, metadataSessionIds: isProjectChat ? [] : [sid] });
            if (isProjectChat) {
                scheduleComposerPrefSave(sid);
            }
            else if (!sessionPrivateMode(sid)) {
                void pushSessionMetadataToServer(sid).catch(() => { });
            }
        }
        const prevMedia = prev.imageGeneration || prev.videoGeneration || prev.speechGeneration;
        const nextMedia = next.imageGeneration || next.videoGeneration || next.speechGeneration;
        if (!prevMedia && nextMedia && sid) {
            const currentId = selectedModelRef.current || model;
            if (currentId && !modelBeforeMediaToolsRef.current[sid]) {
                modelBeforeMediaToolsRef.current[sid] = currentId;
            }
        }
        if (prevMedia && !nextMedia) {
            const saved = sid ? modelBeforeMediaToolsRef.current[sid] : "";
            if (sid)
                delete modelBeforeMediaToolsRef.current[sid];
            const restoreId = (saved || defaultModel || "").trim();
            const found = restoreId ? models.find((m) => m.id === restoreId) : undefined;
            const fallbackId = found?.id || resolveNewChatModel(models, undefined, defaultModel);
            if (fallbackId && fallbackId !== (selectedModelRef.current || model)) {
                pickModel(fallbackId);
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
                        chatToolsRef.current = withVoice;
                        setChatTools(withVoice);
                        if (sid) {
                            persistSessions((prev) => prev.map((s) => s.id === sid
                                ? { ...s, tools: { ...withVoice }, toolsTouched: true, updatedAt: Date.now() }
                                : s), { debounce: false, metadataSessionIds: isProjectChat ? [] : [sid] });
                        }
                    }
                    pickModel(fallback.id);
                    return;
                }
                setChatError("No speech-capable model is available. Enable one in Admin → Models.");
            }
            else {
                const remappedVoice = resolveSpeechVoiceForModel(current, next.speechVoice);
                if (remappedVoice !== next.speechVoice) {
                    const withVoice = { ...next, speechVoice: remappedVoice };
                    chatToolsRef.current = withVoice;
                    setChatTools(withVoice);
                    if (sid) {
                        persistSessions((prev) => prev.map((s) => s.id === sid
                            ? { ...s, tools: { ...withVoice }, toolsTouched: true, updatedAt: Date.now() }
                            : s), { debounce: false, metadataSessionIds: isProjectChat ? [] : [sid] });
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
                    setChatError(`${current.name} is not available for Code Interpreter${reason ? ` (${reason})` : ""}. Switched to ${fallback.name}.`);
                    pickModel(fallback.id);
                    return;
                }
                if (reason)
                    setChatError(reason);
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
    function sessionMessagesForQueue(sessionId) {
        const session = sessionsRef.current.find((s) => s.id === sessionId);
        if (session)
            return session.messages;
        if (sessionId === activeIdRef.current)
            return messagesRef.current;
        return [];
    }
    function canProcessPromptQueue(sessionId) {
        if (abortControllersRef.current[sessionId])
            return false;
        if (isBackgroundImageRunning(sessionId))
            return false;
        if (isBackgroundVideoRunning(sessionId))
            return false;
        if (isBackgroundSpeechRunning(sessionId))
            return false;
        if (streamingSessionsRef.current[sessionId])
            return false;
        return !sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
    }
    function isSessionBusyForSend(sessionId) {
        if (abortControllersRef.current[sessionId])
            return true;
        if (isBackgroundImageRunning(sessionId))
            return true;
        if (isBackgroundVideoRunning(sessionId))
            return true;
        if (isBackgroundSpeechRunning(sessionId))
            return true;
        if (streamingSessionsRef.current[sessionId])
            return true;
        return sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId));
    }
    function clearStaleStreamingFlag(sessionId) {
        if (!streamingSessionsRef.current[sessionId])
            return;
        if (abortControllersRef.current[sessionId])
            return;
        if (isBackgroundImageRunning(sessionId))
            return;
        if (isBackgroundVideoRunning(sessionId))
            return;
        if (isBackgroundSpeechRunning(sessionId))
            return;
        if (sessionHasInFlightGeneration(sessionMessagesForQueue(sessionId)))
            return;
        setSessionStreaming(sessionId, false);
    }
    function tryDrainPromptQueue(sessionId) {
        if (!promptQueuesRef.current[sessionId]?.length)
            return;
        clearStaleStreamingFlag(sessionId);
        if (!canProcessPromptQueue(sessionId))
            return;
        void drainSessionQueue(sessionId);
    }
    function setTurnPhase(sessionId, phase) {
        const next = { ...turnPhasesRef.current };
        if (phase) {
            next[sessionId] = phase;
        }
        else {
            delete next[sessionId];
        }
        turnPhasesRef.current = next;
        setTurnPhases({ ...next });
    }
    function setSessionStreaming(sessionId, value) {
        const next = { ...streamingSessionsRef.current };
        if (value) {
            if (next[sessionId])
                return;
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
    async function copyMessageContent(content, key) {
        const text = displayTextForMessage(content || "").trim();
        if (!text)
            return;
        const ok = await copyTextToClipboard(text);
        if (!ok) {
            setChatError("Copy failed. Please try again.");
            return;
        }
        setCopiedMessageKey(key);
        window.setTimeout(() => setCopiedMessageKey((prev) => (prev === key ? null : prev)), 1400);
    }
    async function rateAssistantMessage(index, rating) {
        const sid = activeIdRef.current;
        const current = messagesRef.current[index];
        if (!sid || !current?.id || current.role !== "assistant")
            return;
        const previous = current.feedback;
        const nextRating = previous?.rating === rating ? 0 : rating;
        const applyFeedback = (feedback) => {
            const nextMessages = messagesRef.current.map((message, messageIndex) => messageIndex === index ? { ...message, feedback } : message);
            messagesRef.current = nextMessages;
            setMessages(nextMessages);
            setSessions((prev) => {
                const next = prev.map((session) => session.id === sid ? { ...session, messages: nextMessages } : session);
                sessionsRef.current = next;
                return next;
            });
        };
        applyFeedback(nextRating === 0 ? undefined : { rating: nextRating });
        try {
            const feedback = await setMessageFeedbackOnServer(sid, current.id, nextRating);
            applyFeedback(feedback);
        }
        catch (error) {
            applyFeedback(previous);
            setChatError(formatApiError(error) || "Could not save feedback.");
        }
    }
    function editUserPrompt(content) {
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
    function deleteUserPromptAt(index) {
        const sid = activeIdRef.current;
        if (!sid)
            return;
        const current = getSessionMessages(sid);
        if (streamingSessions[sid] || sessionHasInFlightGeneration(current)) {
            setChatError("Stop generation before deleting a prompt.");
            return;
        }
        if (index < 0 || index >= current.length)
            return;
        const target = current[index];
        if (!target || target.role !== "user")
            return;
        const next = removePromptThreadFromMessages(current, target, index);
        if (!next)
            return;
        clearSessionMessageSyncQueue(sid);
        if (next.length === 0) {
            void removeChatSession(sid);
            return;
        }
        updateSessionMessages(sid, next);
        if (sessionPrivateMode(sid))
            return;
        void replaceChatSessionMessagesOnServer(sid, next, {
            reconcile: (remote) => removePromptThreadFromMessages(remote, target),
        })
            .then((polled) => {
            setChatError("");
            persistSessions((prev) => {
                const updated = prev.map((s) => s.id === sid
                    ? {
                        ...s,
                        messages: polled.messages,
                        revision: polled.revision,
                        messageCount: polled.messages.length,
                        updatedAt: Date.now(),
                    }
                    : s);
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
    function parseApiError(raw, status) {
        try {
            const j = JSON.parse(raw);
            const detail = j.detail;
            if (detail && typeof detail === "object") {
                return {
                    message: detail.message || raw || `Request failed (${status})`,
                    code: detail.code || j.code,
                    retryAfterSeconds: detail.retry_after_seconds ?? j.retry_after_seconds,
                };
            }
            return {
                message: (typeof detail === "string" ? detail : undefined)
                    || j.message
                    || raw
                    || `Request failed (${status})`,
                code: j.code,
                retryAfterSeconds: j.retry_after_seconds,
            };
        }
        catch {
            return { message: raw || `Request failed (${status})` };
        }
    }
    function stopGenerating(sessionId) {
        const sid = sessionId || activeIdRef.current;
        if (!sid)
            return;
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
        }
        else if (localMsgs.some((m) => m.content === VIDEO_PENDING_MARKER)) {
            applyMessages(sid, buildStoppedVideoMessages(localMsgs));
        }
        else if (localMsgs.some((m) => m.content === SPEECH_PENDING_MARKER)) {
            applyMessages(sid, buildStoppedSpeechMessages(localMsgs));
        }
        else {
            let lastUserIdx = -1;
            for (let i = 0; i < localMsgs.length; i += 1) {
                if (localMsgs[i]?.role === "user")
                    lastUserIdx = i;
            }
            let changed = false;
            const stoppedAt = Date.now();
            const next = localMsgs.map((m, i) => {
                if (i <= lastUserIdx || m.role !== "assistant" || m.receivedAt != null)
                    return m;
                changed = true;
                const content = (m.content || "").trim() ? m.content : "Generation stopped.";
                return { ...m, content, receivedAt: stoppedAt };
            });
            if (changed)
                applyMessages(sid, next);
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
                    if (activeIdRef.current !== sid)
                        return;
                    const mergedMsgs = preferLocalMessagesOverRemote(sid, remoteMsgs);
                    setSessions((prev) => {
                        const next = prev.map((s) => s.id === sid
                            ? {
                                ...s,
                                messages: mergedMsgs,
                                revision,
                                messageCount: Math.max(s.messageCount ?? 0, mergedMsgs.length),
                            }
                            : s);
                        sessionsRef.current = next;
                        return next;
                    });
                    if (activeIdRef.current === sid)
                        setMessages(mergedMsgs);
                    if (!sessionHasInFlightGeneration(mergedMsgs)) {
                        setSessionStreaming(sid, false);
                    }
                })
                    .catch(() => { });
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
                        .catch(() => { })
                        .finally(refreshAfterStop);
                }
                else {
                    refreshAfterStop();
                }
            });
        }
    }
    function setSessionQueue(sessionId, items) {
        promptQueuesRef.current = { ...promptQueuesRef.current, [sessionId]: items };
        setPromptQueues((prev) => ({ ...prev, [sessionId]: items }));
    }
    function enqueuePrompt(sessionId, text, attachments) {
        const item = {
            id: newQueueId(),
            text: text.trim(),
            attachments: cloneProcessedAttachments(attachments),
        };
        const prev = promptQueuesRef.current[sessionId] || [];
        setSessionQueue(sessionId, [...prev, item]);
        queueMicrotask(() => tryDrainPromptQueueRef.current(sessionId));
    }
    function removeQueuedPrompt(sessionId, itemId) {
        const prev = promptQueuesRef.current[sessionId] || [];
        setSessionQueue(sessionId, prev.filter((q) => q.id !== itemId));
    }
    async function clearQueuedPrompts(sessionId) {
        const prev = promptQueuesRef.current[sessionId] || [];
        if (!prev.length)
            return;
        if (prev.length > 2) {
            const ok = await confirm({
                title: "Clear queue",
                message: `Remove ${prev.length} queued prompts? They will not be sent.`,
                confirmLabel: "Clear",
                danger: true,
            });
            if (!ok)
                return;
        }
        setSessionQueue(sessionId, []);
    }
    function editQueuedPrompt(item) {
        const sid = activeIdRef.current;
        if (!sid)
            return;
        const dir = inputDirectionForText(item.text, item.text.length);
        const attachments = item.attachments.map((a) => ({ ...a }));
        setInput(item.text);
        setInputDirection(dir);
        setPendingAttachments(attachments);
        persistActiveComposerDraft({ text: item.text, direction: dir, attachments });
        removeQueuedPrompt(sid, item.id);
        textareaRef.current?.focus();
    }
    function getSessionMessages(sessionId) {
        // Prefer the live active thread — sessionsRef can lag right after creating a chat.
        if (sessionId === activeIdRef.current && messagesRef.current.length) {
            return messagesRef.current;
        }
        return sessionsRef.current.find((s) => s.id === sessionId)?.messages ?? [];
    }
    async function executePromptTurn(sessionId, userText, attachments) {
        if (!userText.trim() && !attachments.length)
            return;
        const validModel = models.find((m) => m.id === model) ||
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
        const userMsg = attachments.length
            ? {
                role: "user",
                content: attachmentMessage({
                    userText: userText.trim(),
                    attachments,
                }),
                sentAt,
                clientMessageId: newClientMessageId(),
                ...(projectAuthorDisplayName ? { authorDisplayName: projectAuthorDisplayName } : {}),
            }
            : {
                role: "user",
                content: userText.trim(),
                sentAt,
                clientMessageId: newClientMessageId(),
                ...(projectAuthorDisplayName ? { authorDisplayName: projectAuthorDisplayName } : {}),
            };
        const prevMsgs = getSessionMessages(sessionId);
        const turnBaseCount = prevMsgs.length;
        pinScrollToBottomRef.current = true;
        const turnSession = sessionsRef.current.find((s) => s.id === sessionId);
        const toolsForTurn = sessionId === activeIdRef.current ? chatToolsRef.current : sessionTools(turnSession);
        const specialistTurn = !sessionPrivateMode(sessionId)
            && agentSelectionForSession(sessionId) !== NO_AGENT_SELECTION;
        const willRouteToImage = !specialistTurn && willRoutePromptToImageGeneration(userMsg.content, toolsForTurn, validModel, prevMsgs);
        const willRouteToVideo = !specialistTurn && willRoutePromptToVideoGeneration(toolsForTurn, validModel);
        const willRouteToSpeech = !specialistTurn && willRoutePromptToSpeechGeneration(toolsForTurn, validModel);
        // Media generation is always single-model (primary only).
        const turnModels = specialistTurn ||
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
            const next = [
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
            }
            catch (err) {
                if (err instanceof DOMException && err.name === "AbortError") {
                    if (!sessionPrivateMode(sessionId)) {
                        void cancelStreamingReplyOnServer(sessionId).catch(() => { });
                        void fetchSessionWithMessages(sessionId).then((remote) => {
                            if (remote?.messages.length && activeIdRef.current === sessionId) {
                                applyMessages(sessionId, remote.messages);
                            }
                        });
                    }
                    return;
                }
                const friendly = friendlyTurnError(err);
                const errAssistant = {
                    role: "assistant",
                    content: `Error: ${friendly}`,
                    receivedAt: Date.now(),
                    clientMessageId: assistantClientMessageId,
                    modelId: validModel.id,
                    modelName: validModel.name,
                };
                const errMsgs = [
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
            }
            finally {
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
                if (controller.signal.aborted)
                    break;
                const turnModel = turnModels[i];
                const assistantClientMessageId = newClientMessageId();
                const placeholder = {
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
                    await runChatTurn(sessionId, withPlaceholder, turnModel, controller, turnBaseCount, {
                        userMessage: userMsg,
                        assistantClientMessageId,
                        includeUserMessage: i === 0,
                    }, {
                        skipTitle: true,
                        skipReconcile: !isLast,
                        // Multi-model text siblings must never fan out to /api/images.
                        allowImageRoute: false,
                    });
                }
                catch (err) {
                    if (err instanceof DOMException && err.name === "AbortError")
                        throw err;
                    const friendly = friendlyTurnError(err);
                    const current = getSessionMessages(sessionId);
                    const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
                    const errAssistant = {
                        role: "assistant",
                        content: `Error: ${friendly}`,
                        receivedAt: Date.now(),
                        clientMessageId: assistantClientMessageId,
                        modelId: turnModel.id,
                        modelName: turnModel.name,
                    };
                    const errMsgs = idx >= 0
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
                    if (!remote?.messages.length)
                        return;
                    if (activeIdRef.current !== sessionId && !sessionsRef.current.some((s) => s.id === sessionId)) {
                        return;
                    }
                    const local = getLocalMessagesForSession(sessionId);
                    // Never let an orphan server error-only thread wipe a local user prompt.
                    if (local.some((m) => m.role === "user") &&
                        !remote.messages.some((m) => m.role === "user") &&
                        remote.messages.every((m) => m.role === "assistant" && (m.content || "").startsWith("Error:"))) {
                        return;
                    }
                    const reconciled = mergeChatMessagesPreferLocal(local, remote.messages, isLocalWorkInFlight(sessionId));
                    applyMessages(sessionId, reconciled);
                });
            }
        }
        catch (err) {
            if (err instanceof DOMException && err.name === "AbortError") {
                if (!sessionPrivateMode(sessionId)) {
                    void cancelStreamingReplyOnServer(sessionId).catch(() => { });
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
        }
        finally {
            delete abortControllersRef.current[sessionId];
            setSessionStreaming(sessionId, false);
        }
    }
    async function drainSessionQueue(sessionId) {
        const inFlight = drainPromisesRef.current[sessionId];
        if (inFlight)
            return inFlight;
        clearStaleStreamingFlag(sessionId);
        if (!canProcessPromptQueue(sessionId))
            return;
        const task = (async () => {
            try {
                while (true) {
                    if (!canProcessPromptQueue(sessionId))
                        break;
                    const queue = promptQueuesRef.current[sessionId];
                    if (!queue?.length)
                        break;
                    const [item, ...rest] = queue;
                    setSessionQueue(sessionId, rest);
                    await executePromptTurn(sessionId, item.text, item.attachments || []);
                }
            }
            finally {
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
    async function downloadImage(url) {
        const triggerDownload = (href) => {
            const safeHref = safeBrowserUrl(href, "download");
            if (!safeHref)
                throw new Error("Blocked unsafe image URL.");
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
                if (!safeBrowserUrl(url, "image"))
                    throw new Error("Blocked unsafe image data URL.");
                triggerDownload(url);
                return;
            }
            const safeUrl = safeBrowserUrl(url, "download");
            if (!safeUrl)
                throw new Error("Blocked unsafe image URL.");
            const a = document.createElement("a");
            a.href = safeUrl;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.download = "alpha-router-generated-image.png";
            document.body.appendChild(a);
            a.click();
            a.remove();
        }
        catch (err) {
            setChatError(formatApiError(err));
        }
    }
    async function downloadVideo(url) {
        const triggerDownload = (href) => {
            const safeHref = safeBrowserUrl(href, "download");
            if (!safeHref)
                throw new Error("Blocked unsafe video URL.");
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
        }
        catch (err) {
            setChatError(formatApiError(err));
        }
    }
    async function downloadSpeech(url, format = "mp3") {
        const ext = (format || "mp3").replace(/[^a-z0-9]/gi, "") || "mp3";
        const triggerDownload = (href) => {
            const safeHref = safeBrowserUrl(href, "download");
            if (!safeHref)
                throw new Error("Blocked unsafe audio URL.");
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
        }
        catch (err) {
            setChatError(formatApiError(err));
        }
    }
    async function openVideoFullSize(url) {
        const openByAnchor = (href) => {
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
        }
        catch (err) {
            setChatError(formatApiError(err));
        }
    }
    function openChatMediaViewer(url) {
        const trimmed = url.trim();
        if (!trimmed)
            return;
        if (findMediaViewerIndex(chatSlideshowItems, trimmed) >= 0) {
            setMediaViewerUrl(trimmed);
        }
    }
    function handleChatMediaViewerIndexChange(nextIndex) {
        setMediaViewerUrl(chatSlideshowItems[nextIndex]?.url ?? null);
    }
    async function openImageFullSize(url) {
        const openByAnchor = (href) => {
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
                if (!safeBrowserUrl(url, "image"))
                    throw new Error("Blocked unsafe image data URL.");
                const [meta, b64] = url.split(",", 2);
                if (!b64)
                    return;
                const mime = meta.match(/^data:(.*?);base64$/)?.[1] || "image/png";
                const binary = atob(b64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i += 1)
                    bytes[i] = binary.charCodeAt(i);
                const blobUrl = URL.createObjectURL(new Blob([bytes], { type: mime }));
                openByAnchor(blobUrl);
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
                return;
            }
            openByAnchor(url);
        }
        catch (err) {
            setChatError(formatApiError(err));
        }
    }
    async function regenerateImage(msgIndex, payload) {
        const sid = activeIdRef.current;
        if (!sid || streamingSessions[sid])
            return;
        const prompt = payload.prompt || "Generate image";
        const modelId = (payload.model && payload.model.startsWith("model::") ? payload.model : "") || model;
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
                referenceImage: payload.reference_image || lastAssistantImageUrl(messages.slice(0, msgIndex)),
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
        }
        catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            setChatError(message);
            if (!sessionPrivateMode(sid)) {
                await syncSessionsFromServer(sid);
            }
        }
        finally {
            setSessionStreaming(sid, false);
        }
    }
    async function retryUserPromptAt(index) {
        const sid = activeIdRef.current;
        if (!sid)
            return;
        if (streamingSessions[sid]) {
            setChatError("Stop generation before retry.");
            return;
        }
        const target = messages[index];
        if (!target || target.role !== "user")
            return;
        // A generated image is persisted immediately after its user prompt. Retry
        // that turn with the concrete model and provider parameters that actually
        // produced the image; do not send Auto Router back through selection.
        const imageAfterPrompt = messages[index + 1]?.role === "assistant"
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
                if (!sessionPrivateMode(sid))
                    await syncSessionsFromServer(sid);
                maybeNotifyMediaReady(sid, messages[index + 1]?.clientMessageId);
            }
            catch (err) {
                const message = err instanceof Error ? err.message : String(err);
                setChatError(message);
                if (!sessionPrivateMode(sid))
                    await syncSessionsFromServer(sid);
            }
            finally {
                setSessionStreaming(sid, false);
            }
            return;
        }
        const validModel = models.find((m) => m.id === model) ||
            models.find((m) => m.external_id === model) ||
            models[0];
        if (!validModel) {
            setChatError("No model available.");
            return;
        }
        if (validModel.id !== model)
            pickModel(validModel.id);
        const toolsForRetry = sid === activeIdRef.current
            ? chatToolsRef.current
            : sessionTools(sessionsRef.current.find((s) => s.id === sid));
        const willRouteToImage = willRoutePromptToImageGeneration(target.content, toolsForRetry, validModel, messages.slice(0, index));
        const willRouteToVideo = willRoutePromptToVideoGeneration(toolsForRetry, validModel);
        const willRouteToSpeech = willRoutePromptToSpeechGeneration(toolsForRetry, validModel);
        const turnModels = willRouteToImage ||
            willRouteToVideo ||
            willRouteToSpeech ||
            toolsForRetry.imageGeneration ||
            toolsForRetry.videoGeneration ||
            toolsForRetry.speechGeneration
            ? [validModel]
            : resolveTurnModels(validModel);
        const base = messages.slice(0, index);
        const turnBaseCount = base.length;
        const userMsg = {
            role: "user",
            content: target.content,
            sentAt: Date.now(),
            clientMessageId: newClientMessageId(),
            ...(projectAuthorDisplayName ? { authorDisplayName: projectAuthorDisplayName } : {}),
        };
        pinScrollToBottomRef.current = true;
        const controller = new AbortController();
        abortControllersRef.current[sid] = controller;
        setSessionStreaming(sid, true);
        setChatError("");
        if (willRouteToImage || willRouteToVideo || willRouteToSpeech) {
            const assistantClientMessageId = newClientMessageId();
            const next = [
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
            }
            catch (err) {
                if (err instanceof DOMException && err.name === "AbortError")
                    return;
                setChatError(friendlyTurnError(err));
            }
            finally {
                delete abortControllersRef.current[sid];
                setSessionStreaming(sid, false);
            }
            return;
        }
        flushSync(() => applyMessages(sid, [...base, userMsg]));
        scrollAfterNewTurn(sid);
        try {
            for (let i = 0; i < turnModels.length; i += 1) {
                if (controller.signal.aborted)
                    break;
                const turnModel = turnModels[i];
                const assistantClientMessageId = newClientMessageId();
                const placeholder = {
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
                    await runChatTurn(sid, withPlaceholder, turnModel, controller, turnBaseCount, {
                        userMessage: userMsg,
                        assistantClientMessageId,
                        includeUserMessage: i === 0,
                    }, {
                        skipTitle: true,
                        skipReconcile: !isLast,
                        allowImageRoute: false,
                    });
                }
                catch (err) {
                    if (err instanceof DOMException && err.name === "AbortError")
                        throw err;
                    const friendly = friendlyTurnError(err);
                    const current = getSessionMessages(sid);
                    const idx = current.findIndex((m) => m.clientMessageId === assistantClientMessageId);
                    const errAssistant = {
                        role: "assistant",
                        content: `Error: ${friendly}`,
                        receivedAt: Date.now(),
                        clientMessageId: assistantClientMessageId,
                        modelId: turnModel.id,
                        modelName: turnModel.name,
                    };
                    const errMsgs = idx >= 0
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
        }
        catch (err) {
            if (err instanceof DOMException && err.name === "AbortError")
                return;
            setChatError(friendlyTurnError(err));
        }
        finally {
            delete abortControllersRef.current[sid];
            setSessionStreaming(sid, false);
        }
    }
    function stopVoiceStream() {
        voiceStreamRef.current?.getTracks().forEach((t) => t.stop());
        voiceStreamRef.current = null;
    }
    async function transcribeVoiceBlob(blob, mimeType, extension, browserFallback) {
        const sid = activeIdRef.current || ensureActiveSession();
        if (sid && sessionPrivateMode(sid)) {
            throw new Error("No speech detected in Private Mode. Try again or type your message.");
        }
        // Layer 2: prefer the server (Whisper) over the browser fallback.
        let baseTranscript = "";
        const fd = new FormData();
        fd.append("file", blob, `voice-${Date.now()}.${extension}`);
        if (sid)
            fd.append("chat_session_id", sid);
        fd.append("language", voiceRecordingLang);
        try {
            const res = await authFetch("/api/chat/voice", {
                method: "POST",
                body: fd,
            });
            if (!res.ok)
                throw new Error(parseApiError(await res.text(), res.status).message);
            const data = (await res.json());
            baseTranscript = (data.transcript || "").trim();
        }
        catch (err) {
            if (browserFallback.trim()) {
                baseTranscript = browserFallback.trim();
            }
            else {
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
            if (refined && refined.trim())
                return refined.trim();
        }
        catch {
            /* fall back to the base transcript */
        }
        return baseTranscript;
    }
    function buildVoiceRefineContext() {
        const recent = messages.slice(-6);
        const out = [];
        for (const m of recent) {
            const content = (m.content || "").trim();
            if (!content)
                continue;
            out.push({
                role: m.role === "assistant" ? "assistant" : "user",
                content: content.length > 300 ? content.slice(0, 300) + "…" : content,
            });
        }
        return out;
    }
    async function refineVoiceTranscript(transcript, modelRef, context) {
        const data = await api("/api/chat/voice/refine", {
            method: "POST",
            body: JSON.stringify({ transcript, model: modelRef || null, context }),
        });
        return (data.transcript || "").trim();
    }
    async function finishVoiceRecording(blob, mimeType, extension, browserFallback) {
        if (!model) {
            setChatError("Choose a model below.");
            return;
        }
        setVoiceBusy(true);
        setChatError("");
        try {
            const transcript = await transcribeVoiceBlob(blob, mimeType, extension, browserFallback);
            const next = transcript.trim();
            if (!next)
                return;
            const base = composerInputRef.current.trim();
            const merged = base ? `${base} ${next}` : next;
            const dir = inputDirectionForText(merged, merged.length);
            setInput(merged);
            setInputDirection(dir);
            persistActiveComposerDraft({ text: merged, direction: dir });
            textareaRef.current?.focus();
        }
        catch (err) {
            reportUserFacingApiError(err);
        }
        finally {
            setVoiceBusy(false);
        }
    }
    async function toggleVoiceRecording() {
        if (voiceBusy)
            return;
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
            const recorderOpts = mimeType
                ? { mimeType, audioBitsPerSecond: 128000 }
                : { audioBitsPerSecond: 128000 };
            const recorder = new MediaRecorder(stream, recorderOpts);
            voiceChunksRef.current = [];
            const speech = new BrowserSpeechCapture();
            browserSpeechRef.current = speech;
            speech.start(voiceRecordingLang);
            recorder.ondataavailable = (ev) => {
                if (ev.data.size > 0)
                    voiceChunksRef.current.push(ev.data);
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
        }
        catch {
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
            revokeScreenshotFrame(screenshotFrameRef.current);
        };
    }, []);
    function removePendingAttachment(index) {
        setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
    }
    function openAttachmentMenu() {
        if (attachUploading)
            return;
        setToolsMenuOpen(false);
        setAgentMenuOpen(false);
        setAttachMenuOpen((open) => !open);
    }
    function closeScreenshotFrame() {
        setScreenshotFrame((prev) => {
            revokeScreenshotFrame(prev);
            return null;
        });
    }
    async function startScreenshotCapture() {
        if (attachUploading)
            return;
        setAttachMenuOpen(false);
        if (pendingAttachmentsRef.current.length >= maxAttachments) {
            setChatError(`You can attach up to ${maxAttachments} files at once.`);
            return;
        }
        setChatError("");
        await new Promise((resolve) => {
            window.setTimeout(resolve, 80);
        });
        try {
            const frame = await captureDisplayFrame();
            setScreenshotFrame(frame);
        }
        catch (err) {
            const permissionMessage = screenshotPermissionErrorMessage(err);
            if (permissionMessage)
                setChatError(permissionMessage);
            else
                reportUserFacingApiError(err);
        }
    }
    async function processPendingAttachmentFiles(files) {
        if (!files.length)
            return;
        const sid = ensureActiveSession();
        if (pendingAttachmentsRef.current.length + files.length > maxAttachments) {
            setChatError(`You can attach up to ${maxAttachments} files at once.`);
            if (fileInputRef.current)
                fileInputRef.current.value = "";
            return;
        }
        setAttachUploading(true);
        setChatError("");
        try {
            if (sid && sessionPrivateMode(sid)) {
                const localAttachments = await processAttachmentFilesLocally(files);
                setPendingAttachments((prev) => [...prev, ...localAttachments].slice(0, maxAttachments));
            }
            else {
                for (const file of files) {
                    validateAttachmentFile(file);
                }
                const fd = new FormData();
                for (const file of files)
                    fd.append("files", file);
                if (sid)
                    fd.append("chat_session_id", sid);
                if (isProjectChat && projectId)
                    fd.append("project_id", projectId);
                const res = await authFetch("/api/chat/attachments/process", {
                    method: "POST",
                    body: fd,
                });
                if (!res.ok)
                    throw new Error(parseApiError(await res.text(), res.status).message);
                const data = (await res.json());
                setPendingAttachments((prev) => [...prev, ...data.attachments].slice(0, maxAttachments));
            }
        }
        catch (err) {
            reportUserFacingApiError(err);
        }
        finally {
            setAttachUploading(false);
            if (fileInputRef.current)
                fileInputRef.current.value = "";
        }
    }
    async function onAttachmentFilesSelected(list) {
        if (!list?.length)
            return;
        await processPendingAttachmentFiles(Array.from(list));
    }
    async function processPendingMediaIds(mediaIds) {
        const ids = [...new Set(mediaIds.filter((id) => Number.isInteger(id) && id > 0))];
        if (!ids.length)
            return;
        const sid = ensureActiveSession();
        if (pendingAttachmentsRef.current.length + ids.length > maxAttachments) {
            setChatError(`You can attach up to ${maxAttachments} files at once.`);
            return;
        }
        if (sid && sessionPrivateMode(sid)) {
            setChatError("Private Mode cannot attach library files through the server. Use Upload file.");
            return;
        }
        setAttachUploading(true);
        setChatError("");
        try {
            const attachments = await attachMediaIds({
                mediaIds: ids,
                chatSessionId: sid,
                projectId: isProjectChat ? projectId : null,
            });
            setPendingAttachments((prev) => [...prev, ...attachments].slice(0, maxAttachments));
        }
        catch (err) {
            reportUserFacingApiError(err);
        }
        finally {
            setAttachUploading(false);
        }
    }
    async function consumeQueuedProjectMedia() {
        if (!isProjectChat || !projectId || readOnly || attachUploading)
            return;
        const payload = readQueuedProjectMediaAttach();
        if (!payload || payload.projectId !== projectId)
            return;
        const mime = (payload.mimeType || "").toLowerCase();
        if (payload.kind === "video" || mime.startsWith("video/")) {
            clearQueuedProjectMediaAttach();
            setChatError("Video files cannot be attached to chat. Use an image or a document.");
            return;
        }
        if (!payload.mediaId) {
            clearQueuedProjectMediaAttach();
            setChatError("Could not attach that file.");
            return;
        }
        try {
            await processPendingMediaIds([payload.mediaId]);
            clearQueuedProjectMediaAttach();
        }
        catch (err) {
            clearQueuedProjectMediaAttach();
            reportUserFacingApiError(err);
        }
    }
    useEffect(() => {
        if (!isProjectChat || !projectId || readOnly)
            return;
        void consumeQueuedProjectMedia();
        const onQueued = () => {
            void consumeQueuedProjectMedia();
        };
        window.addEventListener(PROJECT_MEDIA_ATTACH_EVENT, onQueued);
        return () => window.removeEventListener(PROJECT_MEDIA_ATTACH_EVENT, onQueued);
    }, [isProjectChat, projectId, readOnly, attachUploading]);
    async function send(e) {
        e?.preventDefault();
        if (readOnly)
            return;
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
        if (!text || translateToEngBusy || !textNeedsEnglishTranslation(text))
            return;
        const validModel = resolvePromptAssistModel(models, model);
        if (!validModel) {
            setChatError("No text model is available for translation. Enable one in Admin → Models.");
            return;
        }
        // Video prompts want the same visual-prompt phrasing as image prompts.
        const assistContext = chatTools.imageGeneration || chatTools.videoGeneration || chatTools.speechGeneration
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
        }
        catch (e) {
            const message = e instanceof Error && e.message ? e.message : "";
            setChatError(message || "Couldn't translate to English. Try again or send as is.");
        }
        finally {
            setTranslateToEngBusy(false);
        }
    }
    function onComposerInput(e) {
        const value = e.target.value;
        setInput(value);
        const caret = e.target.selectionStart ?? value.length;
        setInputDirection(inputDirectionForText(value, caret));
    }
    function onComposerSelect(e) {
        const el = e.currentTarget;
        setInputDirection(inputDirectionForText(el.value, el.selectionStart ?? el.value.length));
    }
    async function onComposerPaste(e) {
        const clipboard = e.clipboardData;
        if (!clipboard)
            return;
        const files = [];
        for (const item of clipboard.items) {
            if (item.kind !== "file")
                continue;
            const file = item.getAsFile();
            if (file)
                files.push(file);
        }
        if (!files.length)
            return;
        e.preventDefault();
        const list = new DataTransfer();
        for (const file of files)
            list.items.add(file);
        await onAttachmentFilesSelected(list.files);
    }
    function onKeyDown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }
    function isEmptyStreamingAssistant(index) {
        if (!isSessionStreaming || messages[index]?.role !== "assistant" || messages[index]?.content) {
            return false;
        }
        let lastUserIdx = -1;
        for (let j = 0; j < messages.length; j += 1) {
            if (messages[j]?.role === "user")
                lastUserIdx = j;
        }
        return index > lastUserIdx;
    }
    return (_jsxs("div", { className: `alpha-router-app${isProjectChat ? " alpha-router-app--project" : ""}${hideChatSidebar ? " alpha-router-app--hide-chat-sidebar" : ""}`, "data-persian-font": persianFont || undefined, children: [_jsx(ChatModelPickerModal, { open: modelPickerMode != null, mode: modelPickerMode || "replace", models: pickerModels, selectedIds: selectedModelIds, defaultModelId: defaultModel, onClose: () => setModelPickerMode(null), onSelect: (id) => modelPickerMode === "append" ? appendModelSelection(id) : replaceModelSelection(id), onSetDefault: (id) => setAsDefaultModel(id) }), _jsxs("div", { className: "alpha-router-workspace", children: [!hideChatSidebar ? (_jsxs("aside", { className: `alpha-router-sidebar${selectedChatIds.size > 0 ? " is-selecting" : ""}`, children: [isProjectChat && projectSidebarHeader ? projectSidebarHeader : null, _jsxs("div", { className: "alpha-router-sidebar-top", children: [!isProjectChat ? (_jsx("button", { type: "button", className: "alpha-router-icon-btn alpha-router-menu-btn", onClick: () => shellMenu?.openAdminMenu(), onMouseEnter: () => shellMenu?.openAdminMenu(), "aria-label": "Open menu", title: "Menu", children: "\u2630" })) : null, _jsxs("button", { type: "button", className: "alpha-router-new-chat", onClick: startNewChat, disabled: readOnly, title: accountReadOnly ? "Read-only account" : projectReadOnly ? "Viewers cannot start a chat" : undefined, children: [_jsx("span", { className: "alpha-router-new-chat-icon", children: "+" }), "New chat"] })] }), _jsx("div", { className: "alpha-router-sidebar-body", children: _jsxs(_Fragment, { children: [_jsx("input", { type: "search", className: "alpha-router-history-search", placeholder: "Search chats\u2026", value: historySearch, onChange: (e) => setHistorySearch(e.target.value) }), !readOnly && selectedChatIds.size > 0 ? (_jsxs("div", { className: "alpha-router-bulk-bar", role: "toolbar", "aria-label": "Selected chats", children: [_jsxs("span", { className: "alpha-router-bulk-bar__count", children: [selectedChatIds.size, " selected"] }), !isProjectChat ? (_jsx("button", { type: "button", className: "alpha-router-bulk-bar__btn", onClick: () => setMovingSessionIds([...selectedChatIds]), children: "Move" })) : null, _jsx("button", { type: "button", className: "alpha-router-bulk-bar__btn alpha-router-bulk-bar__btn--danger", onClick: () => void deleteSelectedChats(), children: "Delete" }), _jsxs("div", { className: "alpha-router-bulk-bar__secondary", children: [_jsx("button", { type: "button", className: "alpha-router-bulk-bar__btn", onClick: selectAllVisibleChats, disabled: filteredSessions.length > 0 &&
                                                                filteredSessions.every((s) => selectedChatIds.has(s.id)), children: "Select all" }), _jsx("button", { type: "button", className: "alpha-router-bulk-bar__btn", onClick: clearChatSelection, children: "Clear" })] })] })) : null, !readOnly && !isProjectChat && (_jsxs("div", { className: "alpha-router-folder-create", children: [_jsx("input", { type: "text", placeholder: "New folder\u2026", value: newFolderName, onChange: (e) => setNewFolderName(e.target.value), onKeyDown: (e) => {
                                                        if (e.key === "Enter") {
                                                            e.preventDefault();
                                                            addFolder();
                                                        }
                                                    } }), _jsx("button", { type: "button", onClick: addFolder, disabled: !newFolderName.trim(), children: "+" })] })), !isProjectChat ? (_jsx("div", { className: "alpha-router-folder-group", children: folders.map((f) => (_jsxs("div", { className: `alpha-router-folder-row${dropFolderId === f.id ? " is-drop-target" : ""}${f.color ? " has-color" : ""}`, style: f.color
                                                    ? { "--folder-accent": f.color }
                                                    : undefined, onDragOver: (e) => {
                                                    e.preventDefault();
                                                    setDropFolderId(f.id);
                                                }, onDragLeave: () => setDropFolderId((prev) => (prev === f.id ? null : prev)), onDrop: (e) => {
                                                    e.preventDefault();
                                                    if (draggingSessionId &&
                                                        selectedChatIds.size > 0 &&
                                                        selectedChatIds.has(draggingSessionId)) {
                                                        moveSessionsToFolder([...selectedChatIds], f.id);
                                                    }
                                                    else if (draggingSessionId) {
                                                        moveSessionToFolder(draggingSessionId, f.id);
                                                    }
                                                }, children: [_jsxs("div", { className: "alpha-router-folder-title", children: [_jsx("button", { type: "button", className: "alpha-router-folder-toggle", onClick: () => toggleFolderCollapse(f.id), "aria-label": collapsedFolders[f.id] ? "Expand folder" : "Collapse folder", title: collapsedFolders[f.id] ? "Expand" : "Collapse", children: collapsedFolders[f.id] ? "▸" : "▾" }), _jsx("span", { className: "alpha-router-folder-icon", "aria-hidden": true, children: _jsx(IconFolder, {}) }), renamingFolderId === f.id ? (_jsx("form", { className: "alpha-router-folder-rename", onSubmit: (e) => {
                                                                    e.preventDefault();
                                                                    commitRenameFolder();
                                                                }, children: _jsx("input", { value: renamingFolderName, onChange: (e) => setRenamingFolderName(e.target.value), onBlur: commitRenameFolder, autoFocus: true }) })) : (_jsx("strong", { children: f.name })), renamingFolderId !== f.id && !readOnly ? (_jsx("div", { className: "alpha-router-folder-title-actions", onMouseDown: (e) => e.stopPropagation(), onClick: (e) => e.stopPropagation(), children: _jsx(RowActionsMenu, { label: "Actions", menuClassName: "row-actions-menu--sidebar", actions: [
                                                                        { label: "Rename", onClick: () => startRenameFolder(f) },
                                                                        { label: "Change color", onClick: () => setColorPickerFolderId(f.id) },
                                                                        {
                                                                            label: "Delete",
                                                                            onClick: () => void confirmDeleteFolder(f),
                                                                            danger: true,
                                                                        },
                                                                    ] }) })) : null] }), !collapsedFolders[f.id] ? (_jsxs("ul", { className: "alpha-router-history alpha-router-history-in-folder", children: [(sessionsByFolder[f.id] || []).map((s) => renderSessionRow(s)), (sessionsByFolder[f.id] || []).length === 0 && (_jsx("li", { className: "alpha-router-history-empty", children: "Drop chats here" }))] })) : null] }, f.id))) })) : null, messageSearchHits.length > 0 && historySearch.trim().length >= 2 ? (_jsx("ul", { className: "alpha-router-history alpha-router-history-search-hits", children: messageSearchHits.map((hit) => (_jsx("li", { children: _jsxs("button", { type: "button", className: "alpha-router-history-item", onClick: () => selectSession(hit.sessionId), children: [_jsx("span", { className: "alpha-router-history-item__subtitle", children: hit.sessionTitle }), hit.content.slice(0, 80)] }) }, `${hit.sessionId}-${hit.content.slice(0, 24)}`))) })) : null, _jsx("div", { className: "alpha-router-uncategorized-group", children: inSearchMode ? (filteredSessions.length === 0 ? (_jsx("p", { className: "alpha-router-history-empty", children: "No conversations" })) : (_jsx(VirtualSidebarList, { className: "alpha-router-history-scroll", items: rootSessions.map((s) => ({
                                                    id: s.id,
                                                    node: renderSessionRow(s),
                                                })), hasMore: sessions.length < sessionsTotal, loadingMore: sessionsLoadingMore, onLoadMore: () => void loadMoreSessions() }))) : (_jsx(_Fragment, { children: todayRootSessions.length === 0 &&
                                                    pastDaysRootSessions.length === 0 &&
                                                    displayMidCount === 0 &&
                                                    displayOlderCount === 0 ? (_jsx("p", { className: "alpha-router-history-empty", children: "No conversations" })) : (_jsxs(_Fragment, { children: [todayRootSessions.length > 0 ? (_jsxs(_Fragment, { children: [_jsx("div", { className: "alpha-router-history-section-label", children: "today" }), _jsx("ul", { className: "alpha-router-history alpha-router-history-scroll", children: todayRootSessions.map((s) => (_jsx("li", { children: renderSessionRow(s) }, s.id))) })] })) : null, pastDaysRootSessions.length > 0 ? (_jsxs(_Fragment, { children: [_jsx("div", { className: "alpha-router-history-section-label", children: "1\u20133 days ago" }), _jsx("ul", { className: "alpha-router-history alpha-router-history-scroll alpha-router-history-past-days", children: pastDaysRootSessions.map((s) => (_jsx("li", { children: renderSessionRow(s) }, s.id))) })] })) : null, displayMidCount > 0 ? (_jsxs("div", { className: "alpha-router-history-older", children: [_jsxs("button", { type: "button", className: "alpha-router-history-older-toggle", onClick: () => toggleMidDaysSection(), "aria-expanded": midDaysExpanded, children: [_jsx("span", { className: "alpha-router-history-older-chevron", children: midDaysExpanded ? "▾" : "▸" }), "3\u20137 days ago (", displayMidCount, ")"] }), midDaysExpanded ? (midDaysLoading && midDaysRootSessions.length === 0 ? (_jsx("p", { className: "alpha-router-history-empty", children: "Loading\u2026" })) : (_jsxs(_Fragment, { children: [_jsx("ul", { className: "alpha-router-history alpha-router-history-scroll alpha-router-history-older-list", children: midDaysRootSessions.map((s) => (_jsx("li", { children: renderSessionRow(s) }, s.id))) }), midDaysLoadedCount < midDaysTotal ? (_jsx("button", { type: "button", className: "alpha-router-history-older-more", disabled: midDaysLoadingMore, onClick: () => void loadMidDaysChats({ append: true }), children: midDaysLoadingMore ? "Loading…" : "Load more" })) : null] }))) : null] })) : null, displayOlderCount > 0 ? (_jsxs("div", { className: "alpha-router-history-older", children: [_jsxs("button", { type: "button", className: "alpha-router-history-older-toggle", onClick: () => toggleOlderSection(), "aria-expanded": olderExpanded, children: [_jsx("span", { className: "alpha-router-history-older-chevron", children: olderExpanded ? "▾" : "▸" }), "older than 7 days (", displayOlderCount, ")"] }), olderExpanded ? (olderLoading && olderRootSessions.length === 0 ? (_jsx("p", { className: "alpha-router-history-empty", children: "Loading\u2026" })) : (_jsxs(_Fragment, { children: [_jsx("ul", { className: "alpha-router-history alpha-router-history-scroll alpha-router-history-older-list", children: olderRootSessions.map((s) => (_jsx("li", { children: renderSessionRow(s) }, s.id))) }), olderLoadedCount < olderTotal ? (_jsx("button", { type: "button", className: "alpha-router-history-older-more", disabled: olderLoadingMore, onClick: () => void loadOlderChats({ append: true }), children: olderLoadingMore ? "Loading…" : "Load more" })) : null] }))) : null] })) : null] })) })) })] }) })] })) : null, _jsxs("div", { className: "alpha-router-main-column", children: [projectToolbar, mainOverride ? (_jsx("div", { className: "project-main-override", children: mainOverride })) : (_jsxs("section", { className: `alpha-router-main${activePrivateMode ? " alpha-router-main--private" : ""}`, children: [projectBanner, activePrivateMode ? _jsx(PrivateModeStrip, {}) : null, accountReadOnly && _jsx(ReadOnlyBanner, { className: "readonly-account-banner--chat" }), chatError && _jsx("div", { className: "alpha-router-banner", children: chatError }), modelsError && !chatError && _jsx("div", { className: "alpha-router-banner alpha-router-banner-warn", children: modelsError }), pendingHandoffs.map((handoff) => (_jsx(AgentHandoffBanner, { handoff: handoff, busy: handoffBusyId === handoff.id, onAccept: () => void handleAgentHandoff(handoff, "accept"), onDecline: () => void handleAgentHandoff(handoff, "decline") }, handoff.id))), _jsx("div", { className: "alpha-router-messages", ref: messagesScrollRef, children: _jsxs("div", { className: "alpha-router-messages__inner", ref: messagesInnerRef, children: [messagesLoadingOlder ? (_jsx("div", { className: "alpha-router-banner alpha-router-banner-warn", children: "Loading older messages\u2026" })) : null, messages.length === 0 && (_jsx("div", { className: "alpha-router-welcome", children: _jsx("h2", { children: welcomeHeading }) })), messages.map((m, i) => (_jsxs("article", { className: `alpha-router-msg alpha-router-msg-${m.role}${m.modelId ? " alpha-router-msg-multi" : ""}`, children: [m.role === "assistant" && m.agentName ? (_jsxs("div", { className: "alpha-router-msg-agent-label", title: m.agentId ? `Agent ${m.agentId}` : "Specialist Agent", children: [_jsx("span", { "aria-hidden": true }), m.agentName] })) : null, m.role === "assistant" && m.modelName ? (_jsx("div", { className: "alpha-router-msg-model-label", title: m.modelId, children: _jsx(ModelName, { modelId: m.modelId || m.modelName, label: shortModelName(m.modelName, m.modelId || ""), size: 13 }) })) : null, isProjectChat && m.role === "user" && m.authorDisplayName ? (_jsx("div", { className: "alpha-router-msg-author-label", children: m.authorDisplayName })) : null, _jsx("div", { className: "alpha-router-msg-inner", dir: messageDirectionForContent(m.content), children: (() => {
                                                                const attachPayload = readAttachmentMessage(m.content);
                                                                if (attachPayload) {
                                                                    return (_jsx(ChatAttachmentMessage, { payload: attachPayload, onOpenImage: openChatMediaViewer }));
                                                                }
                                                                const audioPayload = readAudioMessage(m.content);
                                                                if (audioPayload) {
                                                                    return (_jsx(ChatAudioMessage, { url: audioPayload.url, transcript: audioPayload.transcript }));
                                                                }
                                                                if (m.content === IMAGE_PENDING_MARKER) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block alpha-router-generated-block--pending", children: _jsxs("div", { className: "alpha-router-generated-image alpha-router-generated-image--loading", role: "status", "aria-live": "polite", "aria-label": "Generating image", children: [_jsx("span", { className: "alpha-router-image-loading__spinner", "aria-hidden": true }), _jsx("span", { className: "alpha-router-image-loading__label", children: "Generating image\u2026" })] }) }));
                                                                }
                                                                if (m.content === VIDEO_PENDING_MARKER) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block alpha-router-generated-block--pending", children: _jsxs("div", { className: "alpha-router-generated-video alpha-router-generated-video--loading", role: "status", "aria-live": "polite", "aria-label": "Generating video", children: [_jsx("span", { className: "alpha-router-image-loading__spinner", "aria-hidden": true }), _jsx("span", { className: "alpha-router-image-loading__label", children: "Generating video\u2026" })] }) }));
                                                                }
                                                                if (m.content === SPEECH_PENDING_MARKER) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block alpha-router-generated-block--pending", children: _jsxs("div", { className: "alpha-router-generated-audio alpha-router-generated-audio--loading", role: "status", "aria-live": "polite", "aria-label": "Generating audio", children: [_jsx("span", { className: "alpha-router-image-loading__spinner", "aria-hidden": true }), _jsx("span", { className: "alpha-router-image-loading__label", children: "Generating speech\u2026" })] }) }));
                                                                }
                                                                const imagePayload = readImageMessage(m.content);
                                                                if (imagePayload) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block", children: _jsx("button", { type: "button", className: "alpha-router-media-open", onClick: () => openChatMediaViewer(imagePayload.url), "aria-label": "Open image", children: _jsx(AuthenticatedImage, { url: imagePayload.url, alt: "Generated", className: "alpha-router-generated-image" }) }) }));
                                                                }
                                                                const videoPayload = readVideoMessage(m.content);
                                                                if (videoPayload) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block", children: _jsx("div", { className: "alpha-router-media-open", role: "button", tabIndex: 0, onClick: () => openChatMediaViewer(videoPayload.url), onKeyDown: (event) => {
                                                                                if (event.key === "Enter" || event.key === " ") {
                                                                                    event.preventDefault();
                                                                                    openChatMediaViewer(videoPayload.url);
                                                                                }
                                                                            }, "aria-label": "Open video", children: _jsx(AuthenticatedVideo, { url: videoPayload.url, className: "alpha-router-generated-video", title: videoPayload.prompt || "Generated video", controls: false }) }) }));
                                                                }
                                                                const speechPayload = readSpeechMessage(m.content);
                                                                if (speechPayload) {
                                                                    return (_jsx("div", { className: "alpha-router-generated-block", children: _jsx(AuthenticatedAudio, { url: speechPayload.url, title: speechPayload.prompt || "Generated speech", meta: {
                                                                                voice: speechPayload.voice,
                                                                                format: speechPayload.format,
                                                                                durationSeconds: speechPayload.duration_seconds,
                                                                                characters: speechPayload.characters,
                                                                            } }) }));
                                                                }
                                                                const mdImage = extractMarkdownImage(m.content || "");
                                                                if (mdImage.imageUrl) {
                                                                    return (_jsxs("div", { className: "alpha-router-generated-block", children: [_jsx("button", { type: "button", className: "alpha-router-media-open", onClick: () => openChatMediaViewer(mdImage.imageUrl), "aria-label": "Open image", children: _jsx("img", { src: safeBrowserUrl(mdImage.imageUrl, "image") ?? "", alt: "Generated", className: "alpha-router-generated-image" }) }), mdImage.text ? (_jsx(MarkdownContent, { content: mdImage.text, className: "alpha-router-markdown" })) : null] }));
                                                                }
                                                                const fallback = m.content || (isEmptyStreamingAssistant(i) && !activeTurnPhase ? "…" : "");
                                                                if (m.role === "assistant") {
                                                                    const streamingThisMessage = isSessionStreaming && i === messages.length - 1;
                                                                    const showTurnStatus = streamingThisMessage && !m.content?.trim() && activeTurnPhase;
                                                                    const displayContent = formatAgentAnswerForDisplay(fallback, m.citations);
                                                                    return (_jsxs(_Fragment, { children: [showTurnStatus ? (_jsxs("p", { className: "alpha-router-turn-status", "aria-live": "polite", "aria-label": `${turnPhaseLabel(activeTurnPhase)}...`, children: [_jsx("span", { className: "alpha-router-turn-status__pulse", "aria-hidden": true }), _jsxs("span", { className: "alpha-router-turn-status__label", children: [turnPhaseLabel(activeTurnPhase), _jsx(TurnStatusDots, {})] })] })) : null, m.content?.trim() || !showTurnStatus ? (_jsx(MarkdownContent, { content: displayContent, className: `alpha-router-markdown${streamingThisMessage ? " alpha-router-markdown--streaming" : ""}`, streaming: streamingThisMessage })) : null] }));
                                                                }
                                                                const plain = readAttachmentMessage(m.content) || readAudioMessage(m.content) ? "" : fallback;
                                                                return plain;
                                                            })() }), m.role === "assistant" ? (_jsx(AgentCitationList, { runId: m.agentRunId, citations: m.citations, onError: reportUserFacingApiError })) : null, _jsxs("div", { className: "alpha-router-msg-actions", children: [m.role === "assistant" &&
                                                                    typeof m.requestLogId === "number" &&
                                                                    m.content !== IMAGE_PENDING_MARKER &&
                                                                    m.content !== VIDEO_PENDING_MARKER &&
                                                                    m.content !== SPEECH_PENDING_MARKER &&
                                                                    !m.streaming &&
                                                                    !(isSessionStreaming && i === messages.length - 1) ? (_jsx(MessageInfoButton, { title: "Cost details", onClick: () => void openMessageCostDetails(m.requestLogId) })) : (_jsx(MessageInfoButton, { title: chatMessageInfoTitle(m, m.role, messages, i) })), (() => {
                                                                    const videoPayload = readVideoMessage(m.content);
                                                                    if (!videoPayload?.url)
                                                                        return null;
                                                                    return (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download", "aria-label": "Download video", onClick: () => void downloadVideo(videoPayload.url), children: _jsx(DownloadIcon, {}) }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Open full size", "aria-label": "Open video full size", onClick: () => {
                                                                                    if (findMediaViewerIndex(chatSlideshowItems, videoPayload.url) >= 0) {
                                                                                        openChatMediaViewer(videoPayload.url);
                                                                                        return;
                                                                                    }
                                                                                    void openVideoFullSize(videoPayload.url);
                                                                                }, children: _jsx(OpenFullSizeIcon, {}) })] }));
                                                                })(), (() => {
                                                                    const speechPayload = readSpeechMessage(m.content);
                                                                    if (!speechPayload?.url)
                                                                        return null;
                                                                    return (_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download", "aria-label": "Download audio", onClick: () => void downloadSpeech(speechPayload.url, speechPayload.format), children: _jsx(DownloadIcon, {}) }));
                                                                })(), (() => {
                                                                    const imagePayload = readImageMessage(m.content);
                                                                    const mdImage = extractMarkdownImage(m.content || "");
                                                                    const imageUrl = imagePayload?.url || mdImage.imageUrl || "";
                                                                    if (!imageUrl)
                                                                        return null;
                                                                    return (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download", "aria-label": "Download image", onClick: () => void downloadImage(imageUrl), children: _jsx(DownloadIcon, {}) }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Open full size", "aria-label": "Open image full size", onClick: () => {
                                                                                    if (findMediaViewerIndex(chatSlideshowItems, imageUrl) >= 0) {
                                                                                        openChatMediaViewer(imageUrl);
                                                                                        return;
                                                                                    }
                                                                                    void openImageFullSize(imageUrl);
                                                                                }, children: _jsx(OpenFullSizeIcon, {}) }), imagePayload ? (_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Regenerate", "aria-label": "Regenerate image", disabled: isSessionStreaming, onClick: () => regenerateImage(i, imagePayload), children: _jsx(RegenerateIcon, {}) })) : null] }));
                                                                })(), m.role === "user" && (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => void retryUserPromptAt(i), title: "Retry", "aria-label": "Retry prompt", children: "\u21BB" }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => void copyMessageContent(m.content, `${activeId}-${i}`), children: copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy" }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => editUserPrompt(m.content), children: "Edit" }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => deleteUserPromptAt(i), children: "Delete" })] })), m.role !== "user" && (_jsxs(_Fragment, { children: [m.id &&
                                                                            !activePrivateMode &&
                                                                            m.content !== IMAGE_PENDING_MARKER &&
                                                                            m.content !== VIDEO_PENDING_MARKER &&
                                                                            m.content !== SPEECH_PENDING_MARKER &&
                                                                            !m.streaming &&
                                                                            !(isSessionStreaming && i === messages.length - 1) ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: `alpha-router-msg-action-btn alpha-router-msg-feedback-btn${m.feedback?.rating === 1 ? " is-active" : ""}`, disabled: readOnly, onClick: () => void rateAssistantMessage(i, 1), title: "Helpful", "aria-label": "Mark response as helpful", "aria-pressed": m.feedback?.rating === 1, children: "\uD83D\uDC4D" }), _jsx("button", { type: "button", className: `alpha-router-msg-action-btn alpha-router-msg-feedback-btn${m.feedback?.rating === -1 ? " is-active" : ""}`, disabled: readOnly, onClick: () => void rateAssistantMessage(i, -1), title: "Not helpful", "aria-label": "Mark response as not helpful", "aria-pressed": m.feedback?.rating === -1, children: "\uD83D\uDC4E" })] })) : null, _jsx("button", { type: "button", className: "alpha-router-msg-action-btn", onClick: () => void copyMessageContent(m.content, `${activeId}-${i}`), children: copiedMessageKey === `${activeId}-${i}` ? "Copied" : "Copy" }), isTextAssistantExportable(m.content || "") ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download CSV", "aria-label": "Download CSV", onClick: () => downloadCsv(`${activeId}-${i}`, m.content || ""), children: _jsx(CsvIcon, {}) }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download PDF", "aria-label": "Download PDF", onClick: () => {
                                                                                        const title = (activeSession?.title || "chat-export").slice(0, 60);
                                                                                        void exportMessagePdf(m.content || "", title).catch((e) => {
                                                                                            console.error("PDF export failed", e);
                                                                                            alert(`PDF export failed: ${e?.message || e}`);
                                                                                        });
                                                                                    }, children: _jsx(PdfIcon, {}) }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download Word", "aria-label": "Download Word document", onClick: () => {
                                                                                        const title = (activeSession?.title || "chat-export").slice(0, 60);
                                                                                        void exportMessageDocx(m.content || "", title).catch((e) => {
                                                                                            console.error("DOCX export failed", e);
                                                                                            alert(`DOCX export failed: ${e?.message || e}`);
                                                                                        });
                                                                                    }, children: _jsx(DocIcon, {}) }), _jsx("button", { type: "button", className: "alpha-router-msg-action-btn alpha-router-msg-action-btn--icon", title: "Download TXT", "aria-label": "Download plain text", onClick: () => {
                                                                                        const title = (activeSession?.title || "chat-export").slice(0, 60);
                                                                                        downloadTxt(title, m.content || "");
                                                                                    }, children: _jsx(TxtIcon, {}) })] })) : null] }))] })] }, `${activeId}-${i}`))), _jsx("div", { ref: endRef })] }) }), _jsxs("footer", { className: "alpha-router-footer", children: [readOnly ? (_jsx("div", { className: "alpha-router-composer alpha-router-composer--readonly card", children: _jsx("p", { className: "muted-text", style: { margin: 0 }, children: "Read-only mode \u2014 browse your chat history above. Sending messages and using models is disabled." }) })) : (_jsxs("form", { className: "alpha-router-composer", onSubmit: send, children: [showScrollToBottomBtn && messages.length > 0 ? (_jsx("button", { type: "button", className: "alpha-router-scroll-to-bottom", onClick: jumpToChatBottom, "aria-label": "Scroll to latest messages", title: "Jump to bottom", children: _jsx("svg", { viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("polyline", { points: "6 9 12 15 18 9" }) }) })) : null, _jsxs("div", { className: `alpha-router-composer-box${agentModeActive ? " is-agent-active" : ""}`, children: [_jsx("input", { ref: fileInputRef, type: "file", className: "alpha-router-file-input", accept: ATTACHMENT_ACCEPT, multiple: true, onChange: (e) => void onAttachmentFilesSelected(e.target.files), tabIndex: -1, "aria-hidden": true }), pendingAttachments.length > 0 ? (_jsx("div", { className: "alpha-router-pending-attachments", children: pendingAttachments.map((a, idx) => (_jsxs("span", { className: "alpha-router-pending-attachment", children: [_jsxs("span", { className: "alpha-router-pending-attachment__name", title: a.name, children: [a.kind === "image" ? "🖼" : "📄", " ", a.name] }), _jsx("button", { type: "button", className: "alpha-router-pending-attachment__remove", onClick: () => removePendingAttachment(idx), "aria-label": `Remove ${a.name}`, children: "\u00D7" })] }, `${a.url}-${idx}`))) })) : null, activeQueue.length > 0 ? (_jsx(PromptQueue, { items: activeQueue.map((item) => ({ id: item.id, preview: queueItemPreview(item) })), expanded: queueExpanded, onToggleExpanded: () => setQueueExpanded((open) => !open), onEdit: (id) => {
                                                                    const item = activeQueue.find((q) => q.id === id);
                                                                    if (item)
                                                                        editQueuedPrompt(item);
                                                                }, onRemove: (id) => {
                                                                    if (activeId)
                                                                        removeQueuedPrompt(activeId, id);
                                                                }, onClearAll: () => {
                                                                    if (activeId)
                                                                        void clearQueuedPrompts(activeId);
                                                                } })) : null, _jsx("textarea", { ref: textareaRef, className: `alpha-router-composer-input alpha-router-composer-input--${inputDirection}${showWelcomeComposerPrompt ? " alpha-router-composer-input--welcome-prompt" : ""}`, value: input, dir: inputDirection, onChange: onComposerInput, onSelect: onComposerSelect, onPaste: (e) => void onComposerPaste(e), onKeyDown: onKeyDown, placeholder: composerPlaceholder, rows: 1 }), _jsxs("div", { className: "alpha-router-composer-bar", children: [_jsxs("div", { className: "alpha-router-model-row", children: [_jsxs("div", { className: "alpha-router-tools-picker", ref: toolsMenuRef, children: [_jsxs("button", { ref: toolsTriggerRef, type: "button", className: "alpha-router-composer-ctrl alpha-router-model-trigger alpha-router-tools-trigger--icon", onClick: () => {
                                                                                            setModelPickerMode(null);
                                                                                            setAttachMenuOpen(false);
                                                                                            setToolsMenuOpen((o) => !o);
                                                                                        }, "aria-expanded": toolsMenuOpen, "aria-haspopup": "menu", "aria-label": "Tools", title: "Tools", children: [_jsx("span", { className: "alpha-router-composer-ctrl__icon", "aria-hidden": true, children: _jsx(ComposerToolsIcon, {}) }), activeToolCount > 0 ? (_jsx("span", { className: "alpha-router-composer-ctrl__badge", children: activeToolCount })) : null] }), _jsx(ServerToolsMenu, { open: toolsMenuOpen, anchorRef: toolsTriggerRef, tools: chatTools, privateMode: activePrivateMode, allowPrivateMode: !isProjectChat, onChange: updateChatTools, onPrivateModeChange: togglePrivateMode, onClose: () => setToolsMenuOpen(false), videoCapabilities: selectedModels[0], speechCapabilities: selectedModels[0] })] }), _jsxs("div", { className: "alpha-router-tools-picker", ref: agentMenuRef, children: [_jsx("button", { ref: agentTriggerRef, type: "button", className: `alpha-router-composer-ctrl alpha-router-agent-ctrl${agentModeActive ? " is-active" : ""}`, onClick: () => {
                                                                                            setModelPickerMode(null);
                                                                                            setToolsMenuOpen(false);
                                                                                            setAttachMenuOpen(false);
                                                                                            setAgentMenuOpen((o) => !o);
                                                                                        }, disabled: readOnly || activePrivateMode || !agentCatalog.length, "aria-expanded": agentMenuOpen, "aria-haspopup": "menu", "aria-label": "Agents", title: activePrivateMode
                                                                                            ? "Agents are unavailable in Private Mode because Agent runs and citations require server-side evidence."
                                                                                            : agentModeActive
                                                                                                ? `${activeAgentName || "Agent"} is on for this chat`
                                                                                                : "Turn on a governed specialist Agent for this chat", children: _jsx("span", { className: "alpha-router-composer-ctrl__icon", "aria-hidden": true, children: _jsx(ComposerAgentIcon, {}) }) }), _jsx(AgentMenu, { open: agentMenuOpen, anchorRef: agentTriggerRef, agents: agentCatalog, selection: activeAgentSelection, disabled: readOnly || isSessionStreaming, disabledReason: isSessionStreaming
                                                                                            ? "Wait for the current answer to finish before changing Agents."
                                                                                            : undefined, onToggle: toggleAgentForActiveSession, onClose: () => setAgentMenuOpen(false) })] }), _jsxs("button", { type: "button", className: `alpha-router-composer-ctrl alpha-router-translate-eng-btn${translateToEngBusy ? " is-busy" : ""}`, onClick: () => void handleTranslateToEng(), disabled: !input.trim() ||
                                                                                    translateToEngBusy ||
                                                                                    !textNeedsEnglishTranslation(input) ||
                                                                                    !model, "aria-busy": translateToEngBusy, "aria-label": translateToEngBusy ? "Translating to English" : "Translate to English", title: translateToEngBusy
                                                                                    ? "Translating…"
                                                                                    : textNeedsEnglishTranslation(input)
                                                                                        ? "Translate composer text to English"
                                                                                        : "Already in English", children: [translateToEngBusy ? (_jsx("span", { className: "alpha-router-composer-ctrl__spinner", "aria-hidden": true })) : (_jsx("span", { className: "alpha-router-composer-ctrl__icon", "aria-hidden": true, children: _jsx(ComposerTranslateIcon, {}) })), _jsx("span", { className: "alpha-router-composer-ctrl__label", children: "To ENG" })] })] }), _jsxs("div", { className: "alpha-router-send-group", children: [isStopVisible ? (_jsx("button", { type: "button", className: "alpha-router-stop", onClick: () => stopGenerating(activeId), "aria-label": "Stop generating", title: "Stop generating", children: "\u25A0" })) : null, _jsx("button", { ref: attachBtnRef, type: "button", className: "alpha-router-attach-btn", onClick: openAttachmentMenu, disabled: attachUploading || !model, "aria-label": "Attach", "aria-haspopup": "menu", "aria-expanded": attachMenuOpen, title: "Attach file, screenshot, or Media", children: _jsx("svg", { viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor", strokeWidth: "2", children: _jsx("path", { d: "m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.64 16.2a2 2 0 0 1-2.83-2.83l8.49-8.49" }) }) }), _jsx(ComposerAttachMenu, { open: attachMenuOpen, anchorRef: attachBtnRef, onClose: () => setAttachMenuOpen(false), onUpload: () => {
                                                                                    setAttachMenuOpen(false);
                                                                                    fileInputRef.current?.click();
                                                                                }, onScreenshot: () => {
                                                                                    void startScreenshotCapture();
                                                                                }, onFromMedia: () => {
                                                                                    setAttachMenuOpen(false);
                                                                                    setMediaPickerOpen(true);
                                                                                } }), _jsx("button", { type: "button", className: voiceRecording ? "alpha-router-stop alpha-router-voice-btn--recording" : "alpha-router-voice-btn", onClick: () => void toggleVoiceRecording(), disabled: voiceBusy || !model, "aria-label": voiceRecording ? "Stop recording" : "Record voice message", title: voiceRecording ? "Stop and insert text" : "Record voice → text in box", children: voiceRecording ? ("■") : (_jsx("svg", { viewBox: "0 0 24 24", width: "18", height: "18", fill: "currentColor", "aria-hidden": true, children: _jsx("path", { d: "M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V19H9v2h6v-2h-2v-1.08A7 7 0 0 0 19 11h-2z" }) })) }), _jsx("button", { type: "submit", className: "alpha-router-send", disabled: (!input.trim() && !pendingAttachments.length) ||
                                                                                    !model ||
                                                                                    voiceBusy ||
                                                                                    attachUploading, "aria-label": isSessionStreaming ? "Queue message" : "Send message", title: isSessionStreaming ? "Add to queue" : "Send message", children: "\u2191" })] })] })] })] })), _jsxs("p", { className: "alpha-router-disclaimer", children: [PRODUCT_NAME, " can make mistakes. Check important info."] })] })] }))] })] }), _jsx(ColorPickerModal, { open: !!colorPickerFolderId, title: "Folder color", value: folders.find((f) => f.id === colorPickerFolderId)?.color ?? null, onClose: () => setColorPickerFolderId(null), onChange: (color) => {
                    if (colorPickerFolderId)
                        setFolderColor(colorPickerFolderId, color);
                } }), _jsx(MoveToFolderModal, { open: !!movingSessionIds?.length, folders: folders, currentFolderId: movingSessionIds?.length === 1
                    ? sessions.find((s) => s.id === movingSessionIds[0])?.folderId ?? null
                    : null, onClose: () => setMovingSessionIds(null), onMove: (folderId) => {
                    if (movingSessionIds?.length)
                        moveSessionsToFolder(movingSessionIds, folderId);
                } }), _jsx(RequestLogCostDetailsModal, { open: !!costDetailsLog, log: costDetailsLog, details: costDetails, loading: costDetailsLoading, error: costDetailsError, onClose: closeMessageCostDetails }), _jsx(MediaViewerModal, { items: chatSlideshowItems, index: mediaViewerIndex >= 0 ? mediaViewerIndex : null, onClose: () => setMediaViewerUrl(null), onIndexChange: handleChatMediaViewerIndexChange, onOpenExternal: (item) => {
                    if (item.kind === "video")
                        void openVideoFullSize(item.url);
                    else
                        void openImageFullSize(item.url);
                } }), _jsx(ComposerMediaPicker, { open: mediaPickerOpen, projectId: isProjectChat ? projectId : null, privateMode: activePrivateMode, remainingSlots: Math.max(0, maxAttachments - pendingAttachments.length), onClose: () => setMediaPickerOpen(false), onPick: async (files) => {
                    setMediaPickerOpen(false);
                    await processPendingAttachmentFiles(files);
                }, onPickMediaIds: async (ids) => {
                    setMediaPickerOpen(false);
                    await processPendingMediaIds(ids);
                } }), _jsx(ScreenshotCropOverlay, { frame: screenshotFrame, onCancel: closeScreenshotFrame, onConfirm: async (file) => {
                    closeScreenshotFrame();
                    await processPendingAttachmentFiles([file]);
                } })] }));
}
