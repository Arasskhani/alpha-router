export function pickVoiceRecordingMime() {
    const candidates = [
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
export function getSpeechRecognitionCtor() {
    const w = window;
    return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}
/** Map a stored voice-recording language code ("en"|"fa") to a BCP-47 locale. */
export function voiceLangToLocale(lang) {
    const norm = (lang || "").trim().toLowerCase();
    if (norm === "fa")
        return "fa-IR";
    return "en-US";
}
export class BrowserSpeechCapture {
    recognition = null;
    transcript = "";
    start(lang) {
        const Ctor = getSpeechRecognitionCtor();
        if (!Ctor)
            return false;
        this.transcript = "";
        const rec = new Ctor();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = voiceLangToLocale(lang);
        rec.onresult = (event) => {
            let full = "";
            for (let i = 0; i < event.results.length; i += 1) {
                full += event.results[i]?.[0]?.transcript || "";
            }
            if (full)
                this.transcript = full;
        };
        rec.onerror = () => {
            /* browser STT is best-effort only */
        };
        try {
            rec.start();
            this.recognition = rec;
            return true;
        }
        catch {
            this.recognition = null;
            return false;
        }
    }
    stop() {
        const text = this.transcript.trim();
        if (this.recognition) {
            try {
                this.recognition.stop();
            }
            catch {
                /* ignore */
            }
            this.recognition = null;
        }
        this.transcript = "";
        return text;
    }
}
