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
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

export function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/** Map a stored voice-recording language code ("en"|"fa") to a BCP-47 locale. */
export function voiceLangToLocale(lang?: string | null): string {
  const norm = (lang || "").trim().toLowerCase();
  if (norm === "fa") return "fa-IR";
  return "en-US";
}

export class BrowserSpeechCapture {
  private recognition: SpeechRecognitionInstance | null = null;
  private transcript = "";

  start(lang?: string) {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    this.transcript = "";
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = voiceLangToLocale(lang);
    rec.onresult = (event: SpeechRecognitionResultEvent) => {
      let full = "";
      for (let i = 0; i < event.results.length; i += 1) {
        full += event.results[i]?.[0]?.transcript || "";
      }
      if (full) this.transcript = full;
    };
    rec.onerror = () => {
      /* browser STT is best-effort only */
    };
    try {
      rec.start();
      this.recognition = rec;
      return true;
    } catch {
      this.recognition = null;
      return false;
    }
  }

  stop(): string {
    const text = this.transcript.trim();
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch {
        /* ignore */
      }
      this.recognition = null;
    }
    this.transcript = "";
    return text;
  }
}
