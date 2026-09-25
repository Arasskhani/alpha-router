/**
 * Quick prompts: typing / at the start of the composer lists them, and
 * choosing one puts its text in the composer.
 *
 * A few are built in; the user saves their own. Saved prompts stay in this
 * browser (storage.local) - never storage.sync, which would copy them to the
 * browser vendor's servers.
 */

export type Prompt = {
  id: string;
  /** Typed after the slash: lower-case letters, digits and dashes. */
  name: string;
  text: string;
  builtIn?: boolean;
  /** Turns on "This page" when the page may go. */
  attachPage?: boolean;
};

export const BUILT_IN_PROMPTS: Prompt[] = [
  { id: "built-in:summarize", name: "summarize", text: "Summarize this page.", builtIn: true, attachPage: true },
  { id: "built-in:explain", name: "explain", text: "Explain this in simple words:", builtIn: true },
  { id: "built-in:translate", name: "translate", text: "Translate this to Persian:", builtIn: true },
  { id: "built-in:reply", name: "reply", text: "Draft a short, polite reply to this:", builtIn: true },
  { id: "built-in:improve", name: "improve", text: "Improve the writing of this, keeping its meaning:", builtIn: true },
];

const KEY = "alpharouter.prompts";
const MAX_PROMPTS = 50;
export const MAX_PROMPT_TEXT = 4000;
const NAME = /^[a-z0-9][a-z0-9-]{0,31}$/;

function isPrompt(value: unknown): value is Prompt {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.name === "string" &&
    NAME.test(v.name) &&
    typeof v.text === "string" &&
    v.text.length > 0 &&
    v.text.length <= MAX_PROMPT_TEXT
  );
}

/** The user's saved prompts; anything this code did not write is left out. */
export async function loadPrompts(): Promise<Prompt[]> {
  const raw = (await chrome.storage.local.get(KEY))[KEY];
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(isPrompt)
    .slice(0, MAX_PROMPTS)
    .map(({ id, name, text }) => ({ id, name, text }));
}

export async function savePrompts(prompts: Prompt[]): Promise<void> {
  await chrome.storage.local.set({ [KEY]: prompts.slice(0, MAX_PROMPTS).map(({ id, name, text }) => ({ id, name, text })) });
}

/** Calls `onChange` when another page of the extension changes the saved prompts. */
export function watchPrompts(onChange: (prompts: Prompt[]) => void): () => void {
  const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area === "local" && KEY in changes) void loadPrompts().then(onChange);
  };
  chrome.storage.onChanged.addListener(listener);
  return () => chrome.storage.onChanged.removeListener(listener);
}

/** Why a prompt cannot be saved under this name and text, or null. */
export function promptError(name: string, text: string, saved: Prompt[], editing: string | null): string | null {
  if (!NAME.test(name)) return "A name is lower-case letters, digits and dashes, up to 32, starting with a letter or digit.";
  if ([...BUILT_IN_PROMPTS, ...saved].some((prompt) => prompt.name === name && prompt.id !== editing)) {
    return `There is already a prompt called /${name}.`;
  }
  if (!text.trim()) return "Write the prompt's text.";
  if (text.length > MAX_PROMPT_TEXT) return `A prompt is at most ${MAX_PROMPT_TEXT.toLocaleString("en-US")} characters.`;
  if (!editing && saved.length >= MAX_PROMPTS) return `You can save up to ${MAX_PROMPTS} prompts.`;
  return null;
}

/** The "/part" being typed, when the composer holds nothing else before the caret. */
export function slashAt(text: string, caret: number): { query: string } | null {
  const match = /^\/([a-z0-9-]{0,32})$/i.exec(text.slice(0, caret));
  return match ? { query: match[1].toLowerCase() } : null;
}

/** The prompts for what was typed: names that start with it first, then those that contain it. */
export function matchingPrompts(prompts: Prompt[], query: string): Prompt[] {
  if (!query) return prompts;
  const starts = prompts.filter((prompt) => prompt.name.startsWith(query));
  return [...starts, ...prompts.filter((prompt) => !prompt.name.startsWith(query) && prompt.name.includes(query))];
}
