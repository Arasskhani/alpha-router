export function pickVoiceRecordingMime(): { mimeType: string; extension: string } {
  const candidates: Array<{ mimeType: string; extension: string }> = [
    { mimeType: "audio/webm;codecs=opus", extension: "webm" },
    { mimeType: "audio/webm", extension: "webm" },
    { mimeType: "audio/mp4", extension: "m4a" },
    { mimeType: "audio/ogg;codecs=opus", extension: "ogg" },
  ];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c.mimeType)) {
      return c;
    }
  }
  return { mimeType: "", extension: "webm" };
}

type SpeechRecognitionResultEvent = {
  resultIndex: number;
  results: ArrayLike<{ 0?: { transcript?: string } }>;
};

type SpeechRecognitionInstance = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/** The three values the voice-recording language pref may hold. */
export type VoiceLang = "auto" | "en" | "fa";

/**
 * Coerce any stored/legacy value to a supported voice-recording language.
 *
 * Anything unrecognized becomes "auto" so no language is ever forced on the
 * recognizer by accident — forcing "en" on Persian audio makes Whisper
 * transliterate or translate it.
 */
export function normalizeVoiceLang(lang?: string | null): VoiceLang {
  const norm = (lang || "").trim().toLowerCase();
  if (norm === "fa" || norm === "fas" || norm === "persian" || norm === "farsi") return "fa";
  if (norm === "en" || norm === "eng" || norm === "english") return "en";
  return "auto";
}

/** Map a voice-recording language code to a BCP-47 locale for the browser recognizer. */
function voiceLangToLocale(lang?: string | null): string {
  const norm = normalizeVoiceLang(lang);
  if (norm === "fa") return "fa-IR";
  if (norm === "en") return "en-US";
  // "auto": the Web Speech API has no auto-detect, so follow the browser's own
  // UI language instead of pinning Persian speakers to en-US.
  const nav =
    typeof navigator !== "undefined" ? (navigator.language || "").trim() : "";
  return nav || "en-US";
}

/** Called on every partial update with the full transcript recognized so far. */
export type SpeechPartialHandler = (text: string) => void;

/** A session that ends this fast with nothing recognized is a failure, not silence. */
const _FAILED_SESSION_MS = 500;
/** Give up restarting after this many consecutive fast-empty sessions. */
const _MAX_FAILED_SESSIONS = 3;

export class BrowserSpeechCapture {
  private recognition: SpeechRecognitionInstance | null = null;
  /** Text finalized by earlier recognizer sessions (Chrome ends them on silence). */
  private committed = "";
  /** Text from the session currently running, final and interim combined. */
  private sessionText = "";
  /** True while the user is still holding the mic, so ended sessions respawn. */
  private active = false;
  private onPartial: SpeechPartialHandler | null = null;
  private locale = "";
  private sessionStartedAt = 0;
  private failedSessions = 0;

  private get text(): string {
    if (!this.committed) return this.sessionText.trim();
    if (!this.sessionText) return this.committed.trim();
    return `${this.committed.trimEnd()} ${this.sessionText.trimStart()}`.trim();
  }

  /**
   * Begin recognition. `onPartial` fires on every interim update with the full
   * transcript so far, which is what drives the live composer preview.
   */
  start(lang?: string, onPartial?: SpeechPartialHandler) {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    this.committed = "";
    this.sessionText = "";
    this.failedSessions = 0;
    this.onPartial = onPartial || null;
    this.locale = voiceLangToLocale(lang);
    this.active = true;
    const ok = this.spawn();
    if (!ok) this.active = false;
    return ok;
  }

  /**
   * Start one recognizer session.
   *
   * `continuous = true` is not enough on Chrome: the session still ends after a
   * stretch of silence. Without respawning, a pause mid-sentence would freeze
   * the live preview for the rest of the recording.
   */
  private spawn(): boolean {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = this.locale;
    rec.onresult = (event: SpeechRecognitionResultEvent) => {
      let full = "";
      for (let i = 0; i < event.results.length; i += 1) {
        full += event.results[i]?.[0]?.transcript || "";
      }
      this.sessionText = full;
      this.failedSessions = 0;
      if (this.onPartial) this.onPartial(this.text);
    };
    rec.onerror = () => {
      /* browser STT is best-effort only; onend decides whether to respawn */
    };
    rec.onend = () => {
      const wasFast = Date.now() - this.sessionStartedAt < _FAILED_SESSION_MS;
      if (wasFast && !this.sessionText) this.failedSessions += 1;
      // Sessions end at pauses; without a separator the last word of one and
      // the first of the next ran together ("...doneNow...").
      if (this.sessionText) {
        this.committed = this.committed ? `${this.committed.trimEnd()} ${this.sessionText.trimStart()}` : this.sessionText;
      }
      this.sessionText = "";
      this.recognition = null;
      // Bail out instead of spinning when the recognizer service is unreachable.
      if (this.active && this.failedSessions < _MAX_FAILED_SESSIONS) this.spawn();
    };
    try {
      this.sessionStartedAt = Date.now();
      rec.start();
      this.recognition = rec;
      return true;
    } catch {
      this.recognition = null;
      return false;
    }
  }

  /** True once the recognizer has produced any text this recording. */
  hasText(): boolean {
    return this.text.length > 0;
  }

  stop(): string {
    this.active = false;
    this.onPartial = null;
    const text = this.text;
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch {
        /* ignore */
      }
      this.recognition = null;
    }
    this.committed = "";
    this.sessionText = "";
    return text;
  }
}
