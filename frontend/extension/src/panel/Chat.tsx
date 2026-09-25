import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { ChatStreamError, readChatStream } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { fromOwnPages, isExtensionMessage } from "../lib/messages";
import {
  MAX_PAGE_SITES,
  PageReadError,
  pageRefusal,
  readPage,
  screenshotContext,
  selectionContext,
  type PageContext,
  type SiteRules,
} from "../lib/pageContext";
import { PENDING_ACTION_MAX_AGE_MS, takePendingAction, type PendingAction, type PendingActionKind } from "../lib/pendingAction";
import { insertIntoFocusedField, plainText, type InsertResult } from "../lib/insert";
import { captureTab } from "../lib/screenshot";
import { readablePage } from "../lib/sites";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { compareVersions } from "../lib/version";
import { useActivePage, useSiteAccess } from "./activePage";
import { carriesScreenshots, completionBody, pagesIn, pickModel, textModels, type ChatModel, type Turn } from "./chat";
import { MAX_OTHER_TABS, matchingTabs, mentionAt, tabCandidates, useChosenTabs, type PickableTab } from "./otherTabs";
import PanelMarkdown from "./PanelMarkdown";
import PromptPicker from "./PromptPicker";
import { BUILT_IN_PROMPTS, loadPrompts, matchingPrompts, savePrompts, slashAt, watchPrompts, type Prompt } from "./prompts";
import PromptsView from "./PromptsView";
import TabPicker from "./TabPicker";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.model";

/** What a right-click action asks; the page or the selection goes with it. "Ask" and a screenshot wait for the user's question. */
const ACTION_QUESTIONS: Record<Exclude<PendingActionKind, "ask" | "screenshot">, string> = {
  summarize: "Summarize this page.",
  explain: "Explain the selected text.",
  translate: "Translate the selected text to Persian.",
};

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/** Why an answer did not go into the page. */
const NOT_INSERTED: Record<Exclude<InsertResult, "inserted">, string> = {
  no_field: "Click into a text field on the page first, then choose Insert.",
  sensitive: "Alpharouter does not type into password, card or code fields.",
  moved: "The page changed. Try again.",
};

const NO_IMAGES = "This model does not read images. Choose another model.";
const NO_IMAGES_IN_CHAT = "This chat has a screenshot, which this model cannot read. Choose a model that reads images, or start a new chat.";

function CameraIcon() {
  return (
    <svg className="chip__icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      <path d="M2 5h2.5l1.2-1.8h4.6L11.5 5H14v8H2z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <circle cx="8" cy="9" r="2.3" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function PageIcon() {
  return (
    <svg className="chip__icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      <path d="M4 1.5h5l3 3v10H4z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 1.5v3h3M6 8h4M6 10.5h4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

type Props = {
  me: Me;
  server: string;
  /** The user chose Disconnect. */
  onDisconnect: () => void;
  /** The server ended the session while chatting. */
  onDisconnected: () => void;
};

function describe(err: unknown): string {
  if (err instanceof ApiError || err instanceof ChatStreamError || err instanceof TemporaryError) return err.message;
  return "Something went wrong. Try again.";
}

export default function Chat({ me, server, onDisconnect, onDisconnected }: Props) {
  const [models, setModels] = useState<ChatModel[] | null>(null);
  /** The models could not be loaded; "Try again" loads them again. */
  const [modelsFailed, setModelsFailed] = useState(false);
  const [modelLoads, setModelLoads] = useState(0);
  const [modelId, setModelId] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [privateMode, setPrivateMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [inserted, setInserted] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  // A ref, not state: Stop right after the first Send must know the new id.
  const sessionId = useRef<string | null>(null);
  const log = useRef<HTMLDivElement | null>(null);
  const disconnected = useRef(onDisconnected);
  const activePage = useActivePage();
  const target = me.features.page_context ? (activePage?.target ?? null) : null;
  const siteAccess = useSiteAccess(target?.pattern ?? null);
  // "This page" is chosen for one tab and origin: switching tabs or sites turns it off.
  const [attachFor, setAttachFor] = useState<{ tabId: number; origin: string } | null>(null);
  const [reading, setReading] = useState(false);
  /** Text selected on a page ("Ask Alpharouter about…"), sent with the next question. */
  const [selections, setSelections] = useState<PageContext[]>([]);
  /** Other tabs added to the next question. */
  const otherTabs = useChosenTabs();
  /** A screenshot of the page, sent with the next question. */
  const [shot, setShot] = useState<PageContext | null>(null);
  /** The user's saved prompts, and the list shown while a /part is typed. */
  const [savedPrompts, setSavedPrompts] = useState<Prompt[]>([]);
  const [promptPicker, setPromptPicker] = useState<{ query: string; active: number } | null>(null);
  const [showPrompts, setShowPrompts] = useState(false);
  // Chrome takes a screenshot from the panel only with access to every site.
  const allSites = useSiteAccess(me.features.page_context ? "<all_urls>" : null);
  /** The list of tabs to add: opened with "+ Tab", or by typing @ and part of a title. */
  const [picker, setPicker] = useState<{
    tabs: PickableTab[] | null;
    mention: { start: number; query: string } | null;
    active: number;
  } | null>(null);
  // Refs for the right-click actions, which arrive from Chrome at any time.
  const modelRef = useRef("");
  const busyRef = useRef(false);
  const waitingAction = useRef<PendingAction | null>(null);
  /** Right-click actions already taken here: each runs once, however often the panel is told. */
  const takenActions = useRef(new Set<string>());
  const actionHandler = useRef<(action: PendingAction) => void>(() => undefined);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  // Raised by Stop, New chat and Private: a page still being read for the
  // question before is then dropped, not sent into what the user moved on to.
  const generation = useRef(0);
  const rules = useMemo<SiteRules>(
    () => ({
      policy: { allowed_sites: me.policy?.allowed_sites ?? [], blocked_sites: me.policy?.blocked_sites ?? [] },
      serverHost: hostOf(server),
    }),
    [me.policy, server],
  );

  useEffect(() => {
    disconnected.current = onDisconnected;
  }, [onDisconnected]);

  useEffect(() => {
    let active = true;
    Promise.all([getClient().api.json<ChatModel[]>("/api/chat/models"), chrome.storage.local.get(MODEL_KEY)])
      .then(([rows, stored]) => {
        if (!active) return;
        const usable = textModels(rows);
        const picked = pickModel(usable, typeof stored[MODEL_KEY] === "string" ? stored[MODEL_KEY] : null)?.id ?? "";
        setModels(usable);
        setModelsFailed(false);
        setModelId(picked);
        modelRef.current = picked;
        // A right-click action that opened the panel waited for the models -
        // across a failed load too, while it is still fresh.
        const waiting = waitingAction.current;
        if (waiting && picked) {
          waitingAction.current = null;
          if (Date.now() - waiting.createdAt <= PENDING_ACTION_MAX_AGE_MS) actionHandler.current(waiting);
        }
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof DisconnectedError) {
          disconnected.current();
          return;
        }
        setModels([]);
        setModelsFailed(true);
        setBanner(describe(err));
      });
    return () => {
      active = false;
    };
  }, [modelLoads]);

  function loadModelsAgain() {
    setModels(null);
    setModelsFailed(false);
    setBanner("");
    setModelLoads((n) => n + 1);
  }

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(() => {
    let active = true;
    loadPrompts()
      .then((prompts) => {
        if (active) setSavedPrompts(prompts);
      })
      .catch(() => undefined);
    const stop = watchPrompts((prompts) => {
      if (active) setSavedPrompts(prompts);
    });
    return () => {
      active = false;
      stop();
    };
  }, []);

  // The latest render's handler: the listener below lives as long as the panel.
  useEffect(() => {
    actionHandler.current = (action) => void runAction(action);
  });

  useEffect(() => {
    let active = true;
    const check = () => {
      chrome.windows
        .getCurrent()
        .then((win) => (win.id === undefined ? null : takePendingAction(win.id)))
        .then((action) => {
          // Two checks at once can both find the action before either takes it away.
          if (!active || !action || takenActions.current.has(action.id)) return;
          takenActions.current.add(action.id);
          if (modelRef.current) actionHandler.current(action);
          else waitingAction.current = action;
        })
        .catch(() => undefined);
    };
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      if (fromOwnPages(sender) && isExtensionMessage(message) && message.type === "pending-action") check();
    };
    check();
    chrome.runtime.onMessage.addListener(listener);
    return () => {
      active = false;
      chrome.runtime.onMessage.removeListener(listener);
    };
  }, []);

  const version = chrome.runtime.getManifest().version;
  const tooOld = compareVersions(version, me.extension.min_version || "0") < 0;
  const newer = me.extension.latest_version && compareVersions(version, me.extension.latest_version) < 0;
  const attached = Boolean(
    target && activePage && attachFor && attachFor.tabId === activePage.tabId && attachFor.origin === target.origin,
  );
  const pageModels = me.policy?.page_content_models ?? [];

  /** Why this site's pages cannot go to this model, if they cannot. */
  function pageBlockFor(host: string, model: string): string | null {
    return (
      pageRefusal(host, rules) ??
      (pageModels.length && !pageModels.includes(model)
        ? "Your administrator does not allow pages to be sent to this model. Choose another model."
        : null)
    );
  }

  /** "This page", unless the rules keep it from going right now. */
  const pageBlock = target ? pageBlockFor(target.host, modelId) : null;
  const readsImages = Boolean(models?.find((model) => model.id === modelId)?.supports_vision);
  const canScreenshot = me.features.page_context && allSites === true && Boolean(target && activePage);

  async function takeScreenshot() {
    if (!target || busyRef.current) return;
    const refused = pageBlockFor(target.host, modelId);
    if (refused) {
      setBanner(refused);
      return;
    }
    try {
      const win = await chrome.windows.getCurrent();
      if (win.id === undefined) throw new Error("no window");
      const image = await captureTab(win.id);
      // What was captured is the tab showing now: it is named by that tab's page.
      const [shown] = await chrome.tabs.query({ active: true, currentWindow: true });
      const taken = shown?.url ? screenshotContext(shown.url, shown.title ?? "", image) : null;
      if (!taken) throw new Error("not a page");
      const refusedNow = pageBlockFor(taken.host, modelId);
      if (refusedNow) {
        setBanner(refusedNow);
        return;
      }
      setShot(taken);
      setBanner("");
    } catch {
      setBanner("Alpharouter could not take a screenshot of this page.");
    }
  }
  const pickerTabs = picker?.tabs ? matchingTabs(picker.tabs, picker.mention?.query ?? "") : null;
  const canAddTab = me.features.page_context && otherTabs.chosen.length < MAX_OTHER_TABS;

  function openPicker(mention: { start: number; query: string } | null) {
    setPicker({ tabs: null, mention, active: 0 });
    const excluded = new Set([...(activePage ? [activePage.tabId] : []), ...otherTabs.chosen.map((tab) => tab.tabId)]);
    tabCandidates(excluded)
      .then((tabs) => setPicker((open) => (open ? { ...open, tabs } : open)))
      .catch(() => setPicker((open) => (open ? { ...open, tabs: [] } : open)));
  }

  const shownPrompts = promptPicker ? matchingPrompts([...BUILT_IN_PROMPTS, ...savedPrompts], promptPicker.query) : [];

  /** Follow a "/part" typed at the start: open the quick prompts, narrow them, or close them. */
  function followSlash(text: string, caret: number): boolean {
    const slash = slashAt(text, caret);
    if (slash) {
      setPicker(null);
      setPromptPicker({ query: slash.query, active: 0 });
      return true;
    }
    if (promptPicker) setPromptPicker(null);
    return false;
  }

  /** A quick prompt goes into the composer; the summary one also turns on "This page" when it may go. */
  function choosePrompt(prompt: Prompt) {
    const text = prompt.text.endsWith(":") ? `${prompt.text} ` : prompt.text;
    setDraft(text);
    setPromptPicker(null);
    if (prompt.attachPage && target && activePage && siteAccess && !pageBlockFor(target.host, modelId)) {
      setAttachFor({ tabId: activePage.tabId, origin: target.origin });
    }
    composer.current?.focus();
  }

  async function keepPrompts(prompts: Prompt[]) {
    await savePrompts(prompts);
    setSavedPrompts(prompts);
  }

  /** Follow an "@part" being typed: open the list, narrow it, or close it. */
  function followMention(text: string, caret: number) {
    const mention = canAddTab ? mentionAt(text, caret) : null;
    if (mention) {
      if (picker) setPicker({ ...picker, mention, active: 0 });
      else openPicker(mention);
    } else if (picker?.mention) {
      setPicker(null);
    }
  }

  function tabBlock(tab: PickableTab): string | null {
    return pageBlockFor(tab.target.host, modelId);
  }

  function pickTab(tab: PickableTab) {
    if (tabBlock(tab)) return;
    const mention = picker?.mention ?? null;
    const add = () => {
      otherTabs.add(tab);
      // The "@part" that found the tab has done its job.
      if (mention) setDraft((text) => text.slice(0, mention.start) + text.slice(mention.start + 1 + mention.query.length));
      setPicker(null);
      setBanner("");
    };
    if (tab.granted) {
      add();
      return;
    }
    // Chrome asks the user only while the click or key press is being handled: nothing may come first.
    chrome.permissions
      .request({ origins: [tab.target.pattern] })
      .then((granted) => {
        if (granted) add();
        else setBanner(`Alpharouter can read pages on ${tab.target.host} only if you allow it when Chrome asks.`);
      })
      .catch(() => setBanner("Chrome could not ask for permission. Try again."));
  }

  /** A chat carries pages from at most as many sites as the server accepts in one request. */
  function siteLimitError(hosts: string[]): string | null {
    const sites = new Set(pagesIn(turns).map((page) => page.host));
    for (const host of hosts) sites.add(host);
    return sites.size > MAX_PAGE_SITES
      ? `This chat already has pages from ${MAX_PAGE_SITES} sites. Start a new chat to share more.`
      : null;
  }

  function markBusy(value: boolean) {
    busyRef.current = value;
    setBusy(value);
  }

  function chooseModel(id: string) {
    modelRef.current = id;
    setModelId(id);
    void chrome.storage.local.set({ [MODEL_KEY]: id });
  }

  async function nameTheChat(sid: string, question: string, answer: string, model: string) {
    const { api } = getClient();
    try {
      const { title } = await api.json<{ title: string }>("/api/chat/session-title", {
        method: "POST",
        body: JSON.stringify({
          model,
          messages: [
            { role: "user", content: question },
            { role: "assistant", content: answer },
          ],
        }),
      });
      if (title) {
        await api.request(`/api/user/chats/sessions/${encodeURIComponent(sid)}`, {
          method: "PATCH",
          body: JSON.stringify({ title, titleGenerated: true }),
        });
      }
    } catch {
      // The server already titled the chat from the question.
    }
  }

  function togglePage() {
    if (!target || !activePage) return;
    if (attached) {
      setAttachFor(null);
      return;
    }
    const choice = { tabId: activePage.tabId, origin: target.origin };
    if (siteAccess) {
      setAttachFor(choice);
      return;
    }
    const { host } = target;
    // Chrome asks the user only while the click is being handled: nothing may come first.
    chrome.permissions
      .request({ origins: [target.pattern] })
      .then((granted) => {
        if (granted) {
          setAttachFor(choice);
          setBanner("");
        } else {
          setBanner(`Alpharouter can read pages on ${host} only if you allow it when Chrome asks.`);
        }
      })
      .catch(() => setBanner("Chrome could not ask for permission. Try again."));
  }

  /**
   * Read the tabs' pages for the question about to go; the banner says why
   * not, and null comes back - also when the user stopped or moved on meanwhile.
   */
  async function readForQuestion(tabs: Array<{ id: number; url: string; title?: string }>): Promise<PageContext[] | null> {
    const started = generation.current;
    markBusy(true);
    setReading(true);
    setBanner("");
    let current = tabs[0];
    try {
      const pages: PageContext[] = [];
      for (const tab of tabs) {
        current = tab;
        pages.push((await readPage(tab, rules)).page);
        if (started !== generation.current) return null;
      }
      return pages;
    } catch (err) {
      if (started === generation.current) {
        const reason = err instanceof PageReadError ? err.message : "Alpharouter could not read this page.";
        // With several tabs, which one could not be read.
        setBanner(tabs.length > 1 && current?.title ? `“${current.title}”: ${reason}` : reason);
      }
      return null;
    } finally {
      // After Stop the panel is already idle, and may be busy with something new.
      if (started === generation.current) {
        setReading(false);
        markBusy(false);
      }
    }
  }

  /** The server refused a site: its pages leave the conversation, so the next question can go. */
  function dropPagesFrom(host: string) {
    setTurns((all) =>
      all.map((turn) => (turn.pages?.some((page) => page.host === host) ? { ...turn, pages: turn.pages.filter((page) => page.host !== host) } : turn)),
    );
  }

  async function send() {
    const text = draft.trim();
    if (!text || busyRef.current || !modelId) return;
    const pages = [...selections, ...(shot ? [shot] : [])];
    const tab =
      attached && activePage && target ? { id: activePage.tabId, url: activePage.url, host: target.host, title: activePage.title } : null;
    const toRead = [
      ...(tab ? [tab] : []),
      ...otherTabs.chosen.map((other) => ({ id: other.tabId, url: other.url, host: other.target.host, title: other.title })),
    ];
    const hosts = [...pages.map((page) => page.host), ...toRead.map((item) => item.host)];
    const imagesRefused = readsImages ? null : shot ? NO_IMAGES : carriesScreenshots(pagesIn(turns)) ? NO_IMAGES_IN_CHAT : null;
    const refused =
      imagesRefused ?? hosts.map((host) => pageBlockFor(host, modelId)).find(Boolean) ?? (hosts.length ? siteLimitError(hosts) : null);
    if (refused) {
      setBanner(refused);
      return;
    }
    if (toRead.length) {
      const read = await readForQuestion(toRead);
      if (!read) return;
      pages.push(...read);
    }
    setAttachFor(null);
    otherTabs.clear();
    setPicker(null);
    setSelections([]);
    setShot(null);
    setDraft("");
    await sendTurn(text, pages, modelId);
  }

  /** A question for the model, with the pages that go with it. */
  async function sendTurn(text: string, pages: PageContext[], model: string) {
    const user: Turn = { id: crypto.randomUUID(), role: "user", content: text, ...(pages.length ? { pages } : {}) };
    const assistant: Turn = { id: crypto.randomUUID(), role: "assistant", content: "", streaming: true };
    const history = turns;
    if (!privateMode) sessionId.current ??= crypto.randomUUID();
    const sid = privateMode ? null : sessionId.current;
    setTurns([...history, user, assistant]);
    markBusy(true);
    setBanner("");
    const abort = new AbortController();
    controller.current = abort;
    const update = (patch: Partial<Turn>) =>
      setTurns((all) => all.map((turn) => (turn.id === assistant.id ? { ...turn, ...patch } : turn)));
    try {
      const response = await getClient().api.request("/api/chat/completions", {
        method: "POST",
        body: JSON.stringify(
          completionBody({ model, history, user, assistantId: assistant.id, sessionId: sid, sentAt: Date.now() }),
        ),
        signal: abort.signal,
      });
      if (!response.ok) throw await ApiError.from(response);
      const result = await readChatStream(response, { onText: (full) => update({ content: full }) });
      update({ content: result.text, streaming: false });
      if (sid && history.length === 0 && result.text) void nameTheChat(sid, text, result.text, model);
    } catch (err) {
      if (abort.signal.aborted) update({ streaming: false, stopped: true });
      else if (err instanceof DisconnectedError) disconnected.current();
      else {
        if (err instanceof ApiError && err.code === "site_not_allowed" && typeof err.detail.site === "string") {
          dropPagesFrom(err.detail.site);
        }
        update({ streaming: false, error: describe(err) });
      }
    } finally {
      controller.current = null;
      markBusy(false);
    }
  }

  /** A right-click action: summarize the page, or explain, translate or ask about the selection. */
  async function runAction(action: PendingAction) {
    if (!me.features.chat || tooOld) return;
    if (busyRef.current) {
      setBanner("Alpharouter is still answering. Stop it or wait, then try again.");
      return;
    }
    const model = modelRef.current;
    const page = me.features.page_context ? readablePage(action.pageUrl) : null;
    if (!page) {
      setBanner(
        action.kind === "summarize" || !me.features.page_context
          ? "Alpharouter cannot read this page."
          : "Alpharouter cannot read text selected in that part of the page.",
      );
      return;
    }
    const refused = pageBlockFor(page.host, model) ?? siteLimitError([page.host]);
    if (refused) {
      setBanner(refused);
      return;
    }
    if (action.kind === "summarize") {
      const read = await readForQuestion([{ id: action.tabId, url: action.pageUrl }]);
      if (read) await sendTurn(ACTION_QUESTIONS.summarize, read, model);
      return;
    }
    if (action.kind === "screenshot") {
      // Taken by the worker when the menu was clicked: it waits here for the user's question.
      const taken = action.image ? screenshotContext(action.pageUrl, action.title, action.image) : null;
      if (!taken) {
        setBanner("Alpharouter could not take a screenshot of this page.");
        return;
      }
      setShot(taken);
      setBanner("");
      composer.current?.focus();
      return;
    }
    const selected = selectionContext(action.pageUrl, action.title, action.selection);
    if (!selected) {
      setBanner("Select some text on the page first.");
      return;
    }
    setBanner("");
    if (action.kind === "ask") {
      setSelections((all) => [...all.filter((item) => item.text !== selected.text || item.host !== selected.host), selected]);
      composer.current?.focus();
      return;
    }
    await sendTurn(ACTION_QUESTIONS[action.kind], [selected], model);
  }

  function stop() {
    generation.current += 1;
    const inFlight = controller.current;
    if (!inFlight) {
      // Only a page was being read: drop it, and the question stays in the composer.
      setReading(false);
      markBusy(false);
      return;
    }
    inFlight.abort();
    const sid = sessionId.current;
    if (sid && !privateMode) {
      // The server keeps generating for a saved chat until told.
      void getClient()
        .api.request(`/api/user/chat-sessions/${encodeURIComponent(sid)}/cancel-stream`, { method: "POST" })
        .catch(() => undefined);
    }
  }

  function newChat() {
    generation.current += 1;
    if (busy) stop();
    setTurns([]);
    setSelections([]);
    otherTabs.clear();
    setPicker(null);
    setShot(null);
    setBanner("");
    sessionId.current = null;
  }

  function togglePrivate() {
    newChat();
    setPrivateMode((on) => !on);
  }

  /** Put an answer into the field the user left focused in the page next to the panel. */
  function insertAnswer(turn: Turn) {
    if (!target || !activePage) return;
    const refused = pageRefusal(target.host, rules);
    if (refused) {
      setBanner(refused);
      return;
    }
    const tab = { id: activePage.tabId, host: target.host };
    const text = plainText(turn.content);
    if (siteAccess) {
      void insertInto(tab, text, turn.id);
      return;
    }
    // Chrome asks the user only while the click is being handled: nothing may come first.
    chrome.permissions
      .request({ origins: [target.pattern] })
      .then((granted) => {
        if (granted) void insertInto(tab, text, turn.id);
        else setBanner(`Alpharouter can type on ${tab.host} only if you allow it when Chrome asks.`);
      })
      .catch(() => setBanner("Chrome could not ask for permission. Try again."));
  }

  async function insertInto(tab: { id: number; host: string }, text: string, turnId: string) {
    try {
      const [first] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: insertIntoFocusedField,
        args: [text, tab.host],
      });
      const result = first?.result as InsertResult | undefined;
      if (result === "inserted") {
        setBanner("");
        setInserted(turnId);
        window.setTimeout(() => setInserted((id) => (id === turnId ? null : id)), 1500);
      } else {
        setBanner(result ? NOT_INSERTED[result] : "Alpharouter could not type into this page. Reload it and try again.");
      }
    } catch {
      setBanner("Alpharouter could not type into this page. Reload it and try again.");
    }
  }

  async function copy(turn: Turn) {
    try {
      await navigator.clipboard.writeText(turn.content);
      setCopied(turn.id);
      window.setTimeout(() => setCopied((id) => (id === turn.id ? null : id)), 1500);
    } catch {
      setBanner("Copying is not allowed here.");
    }
  }

  if (!me.features.chat || tooOld) {
    return (
      <main className="panel panel__center">
        <h1 className="panel__title">Alpharouter</h1>
        <p className="banner banner--warning" role="status">
          {tooOld
            ? "This copy of the extension is too old for your Alpharouter. Download the new version from Settings → Extension."
            : "The browser extension is not enabled for your account. Ask your administrator if you need it."}
        </p>
        <div className="panel__actions">
          <button type="button" className="btn" onClick={onDisconnect}>
            Disconnect
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="panel chat">
      <header className="chat__header">
        <select
          className="chat__model"
          aria-label="Model"
          value={modelId}
          disabled={!models?.length || busy}
          onChange={(event) => chooseModel(event.target.value)}
        >
          {!models && <option value="">Loading models…</option>}
          {models?.length === 0 && <option value="">No models available</option>}
          {models?.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name}
            </option>
          ))}
        </select>
        {modelsFailed && (
          <button type="button" className="btn btn--quiet" onClick={loadModelsAgain}>
            Try again
          </button>
        )}
        {privateMode && <span className="chat__private">Private</span>}
        <button type="button" className="btn btn--quiet" onClick={newChat}>
          New chat
        </button>
        <details className="chat__menu">
          <summary aria-label="More">⋯</summary>
          <div className="chat__menu-items">
            {me.features.private_mode && (
              <button type="button" className="btn btn--quiet" onClick={togglePrivate}>
                {privateMode ? "Leave Private" : "Private chat"}
              </button>
            )}
            <button type="button" className="btn btn--quiet" onClick={() => setShowPrompts(true)}>
              Saved prompts
            </button>
            <a className="btn btn--quiet" href={`${server}/app/chat`} target="_blank" rel="noopener noreferrer">
              Open Alpharouter
            </a>
            <button type="button" className="btn btn--quiet" onClick={onDisconnect}>
              Disconnect
            </button>
          </div>
        </details>
      </header>

      {newer && (
        <p className="banner banner--warning chat__notice" role="status">
          A new version of the extension is available. Download it from Settings → Extension in Alpharouter.
        </p>
      )}
      {banner && (
        <p className="banner banner--error chat__notice" role="alert">
          {banner}
        </p>
      )}

      {showPrompts ? (
        <PromptsView prompts={savedPrompts} onSave={keepPrompts} onClose={() => setShowPrompts(false)} />
      ) : (
        <>
          <div className="chat__log" role="log" aria-live="polite" ref={log}>
            {turns.length === 0 && (
              <p className="chat__empty">
                {privateMode
                  ? "Private chat: nothing is saved, and it is gone when you start a new chat."
                  : `Ask anything, ${me.user.display_name || me.user.username}. Chats are saved to your Alpharouter history.`}
                {me.features.page_context && " To ask about the page next to this panel, turn on “This page” below."}
              </p>
            )}
            {turns.map((turn) => (
              <article key={turn.id} className={`turn turn--${turn.role}`}>
                {turn.pages?.map((shared, index) =>
                  shared.part === "screenshot" ? (
                    <p key={index} className="turn__page" title={shared.url}>
                      <CameraIcon />
                      <span className="turn__page-title">Screenshot</span>
                      <span className="turn__page-site">{shared.host}</span>
                      {/* Taken in this browser: a data URL, never a remote image. */}
                      <img className="turn__shot" src={shared.image} alt={`Screenshot of ${shared.host}`} />
                    </p>
                  ) : (
                    <p key={index} className="turn__page" title={shared.url}>
                      <PageIcon />
                      <span className="turn__page-title">
                        {shared.part === "selection" ? "Selected text" : shared.title || shared.host}
                      </span>
                      <span className="turn__page-site">{shared.truncated ? `${shared.host}, first part` : shared.host}</span>
                    </p>
                  ),
                )}
                {turn.role === "user" ? <p className="turn__text">{turn.content}</p> : turn.content && <PanelMarkdown text={turn.content} />}
                {turn.streaming && !turn.content && <p className="turn__pending">Thinking…</p>}
                {turn.stopped && <p className="turn__meta">Stopped.</p>}
                {turn.error && (
                  <p className="banner banner--error" role="alert">
                    {turn.error}
                  </p>
                )}
                {turn.role === "assistant" && !turn.streaming && turn.content && (
                  <div className="turn__actions">
                    <button type="button" className="btn btn--quiet turn__copy" aria-label="Copy answer" onClick={() => void copy(turn)}>
                      {copied === turn.id ? "Copied" : "Copy"}
                    </button>
                    {me.features.page_context && target && activePage && (
                      <button
                        type="button"
                        className="btn btn--quiet turn__copy"
                        aria-label="Insert answer into the page"
                        title={`Into the field you left selected on ${target.host}`}
                        onClick={() => insertAnswer(turn)}
                      >
                        {inserted === turn.id ? "Inserted" : "Insert"}
                      </button>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>

          <form
            className="chat__composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            {promptPicker && (
              <PromptPicker
                prompts={shownPrompts}
                active={Math.min(promptPicker.active, Math.max(0, shownPrompts.length - 1))}
                onPick={choosePrompt}
              />
            )}
            {picker && (
              <TabPicker
                tabs={pickerTabs}
                active={pickerTabs?.length ? Math.min(picker.active, pickerTabs.length - 1) : 0}
                blockFor={tabBlock}
                onPick={pickTab}
                onClose={() => setPicker(null)}
              />
            )}
            {(selections.length > 0 || me.features.page_context) && (
              <div className="chat__context">
                {selections.map((selected, index) => (
                  <span key={index} className="chip chip--on chip--static" title={selected.text.slice(0, 300)}>
                    <PageIcon />
                    <span className="chip__label">Selected text</span>
                    <span className="chip__site">{selected.host}</span>
                    <button
                      type="button"
                      className="chip__remove"
                      aria-label={`Remove the text selected on ${selected.host}`}
                      disabled={busy}
                      onClick={() => setSelections((all) => all.filter((_, i) => i !== index))}
                    >
                      ×
                    </button>
                  </span>
                ))}
                {target && activePage && (
                  <button
                    type="button"
                    className={`chip${attached ? " chip--on" : ""}`}
                    aria-pressed={attached}
                    // A page that may not go any more can still be turned off.
                    disabled={busy || (Boolean(pageBlock) && !attached)}
                    onClick={togglePage}
                    title={activePage.url}
                  >
                    <PageIcon />
                    <span className="chip__label">{attached ? "Sending this page" : "This page"}</span>
                    <span className="chip__site">{activePage.title || target.host}</span>
                  </button>
                )}
                {otherTabs.chosen.map((tab) => (
                  <span key={tab.tabId} className="chip chip--on chip--static" title={tab.url}>
                    <PageIcon />
                    <span className="chip__label">Tab</span>
                    <span className="chip__site">{tab.title}</span>
                    <button
                      type="button"
                      className="chip__remove"
                      aria-label={`Remove the tab ${tab.title}`}
                      disabled={busy}
                      onClick={() => otherTabs.remove(tab.tabId)}
                    >
                      ×
                    </button>
                  </span>
                ))}
                {shot && (
                  <span className="chip chip--on chip--static" title={shot.url}>
                    <CameraIcon />
                    <span className="chip__label">Screenshot</span>
                    <span className="chip__site">{shot.host}</span>
                    <button
                      type="button"
                      className="chip__remove"
                      aria-label="Remove the screenshot"
                      disabled={busy}
                      onClick={() => setShot(null)}
                    >
                      ×
                    </button>
                  </span>
                )}
                {canScreenshot && !shot && (
                  <button
                    type="button"
                    className="chip-add"
                    aria-label="Take a screenshot of the page"
                    disabled={busy || Boolean(pageBlock)}
                    onClick={() => void takeScreenshot()}
                  >
                    <CameraIcon />
                    Screenshot
                  </button>
                )}
                {canAddTab && (
                  <button
                    type="button"
                    className="chip-add"
                    aria-label="Add a tab"
                    aria-expanded={Boolean(picker)}
                    disabled={busy}
                    onClick={() => (picker ? setPicker(null) : openPicker(null))}
                  >
                    + Tab
                  </button>
                )}
                {reading && (
                  <span className="chat__context-note" role="status">
                    Reading the page…
                  </span>
                )}
                {!reading && pageBlock && <span className="chat__context-note">{pageBlock}</span>}
                {shot && !readsImages && <span className="chat__context-note">{NO_IMAGES}</span>}
              </div>
            )}
            <textarea
              ref={composer}
              aria-label="Message"
              value={draft}
              rows={2}
              placeholder={privateMode ? "Private message…" : "Message Alpharouter…"}
              onChange={(event) => {
                const caret = event.target.selectionStart ?? event.target.value.length;
                setDraft(event.target.value);
                if (!followSlash(event.target.value, caret)) followMention(event.target.value, caret);
              }}
              onKeyDown={(event) => {
                if (promptPicker) {
                  const count = shownPrompts.length;
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setPromptPicker(null);
                    return;
                  }
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault();
                    const step = event.key === "ArrowDown" ? 1 : -1;
                    setPromptPicker({ ...promptPicker, active: Math.max(0, Math.min(count - 1, promptPicker.active + step)) });
                    return;
                  }
                  if ((event.key === "Enter" || event.key === "Tab") && count > 0 && !event.nativeEvent.isComposing) {
                    // Enter chooses the prompt the list is on; it never sends "/sum".
                    event.preventDefault();
                    choosePrompt(shownPrompts[Math.min(promptPicker.active, count - 1)]);
                    return;
                  }
                }
                if (picker) {
                  const count = pickerTabs?.length ?? 0;
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setPicker(null);
                    return;
                  }
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault();
                    const step = event.key === "ArrowDown" ? 1 : -1;
                    setPicker({ ...picker, active: Math.max(0, Math.min(count - 1, picker.active + step)) });
                    return;
                  }
                  if (event.key === "Enter" && picker.mention && !event.nativeEvent.isComposing) {
                    // Enter picks the tab the list is on; it never sends the question meanwhile.
                    event.preventDefault();
                    if (pickerTabs?.length) pickTab(pickerTabs[Math.min(picker.active, count - 1)]);
                    return;
                  }
                }
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            {busy ? (
              <button type="button" className="btn" onClick={stop}>
                Stop
              </button>
            ) : (
              <button type="submit" className="btn btn--primary" disabled={!draft.trim() || !modelId}>
                Send
              </button>
            )}
          </form>
        </>
      )}
    </main>
  );
}
