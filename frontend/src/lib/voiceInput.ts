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

export class BrowserSpeechCapture {
  private recognition: SpeechRecognitionInstance | null = null;
  private transcript = "";

  start() {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    this.transcript = "";
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = document.documentElement.lang || "fa-IR";
    rec.onresult = (event: SpeechRecognitionResultEvent) => {
      let chunk = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        chunk += event.results[i]?.[0]?.transcript || "";
      }
      if (chunk) this.transcript = chunk;
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
