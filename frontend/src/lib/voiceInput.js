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
/**
 * Coerce any stored/legacy value to a supported voice-recording language.
 *
 * Anything unrecognized becomes "auto" so no language is ever forced on the
 * recognizer by accident — forcing "en" on Persian audio makes Whisper
 * transliterate or translate it.
 */
export function normalizeVoiceLang(lang) {
    const norm = (lang || "").trim().toLowerCase();
    if (norm === "fa" || norm === "fas" || norm === "persian" || norm === "farsi")
        return "fa";
    if (norm === "en" || norm === "eng" || norm === "english")
        return "en";
    return "auto";
}
/** Map a voice-recording language code to a BCP-47 locale for the browser recognizer. */
export function voiceLangToLocale(lang) {
    const norm = normalizeVoiceLang(lang);
    if (norm === "fa")
        return "fa-IR";
    if (norm === "en")
        return "en-US";
    // "auto": the Web Speech API has no auto-detect, so follow the browser's own
    // UI language instead of pinning Persian speakers to en-US.
    const nav = typeof navigator !== "undefined" ? (navigator.language || "").trim() : "";
    return nav || "en-US";
}
/** A session that ends this fast with nothing recognized is a failure, not silence. */
const _FAILED_SESSION_MS = 500;
/** Give up restarting after this many consecutive fast-empty sessions. */
const _MAX_FAILED_SESSIONS = 3;
export class BrowserSpeechCapture {
    recognition = null;
    /** Text finalized by earlier recognizer sessions (Chrome ends them on silence). */
    committed = "";
    /** Text from the session currently running, final and interim combined. */
    sessionText = "";
    /** True while the user is still holding the mic, so ended sessions respawn. */
    active = false;
    onPartial = null;
    locale = "";
    sessionStartedAt = 0;
    failedSessions = 0;
    get text() {
        return (this.committed + this.sessionText).trim();
    }
    /**
     * Begin recognition. `onPartial` fires on every interim update with the full
     * transcript so far, which is what drives the live composer preview.
     */
    start(lang, onPartial) {
        const Ctor = getSpeechRecognitionCtor();
        if (!Ctor)
            return false;
        this.committed = "";
        this.sessionText = "";
        this.failedSessions = 0;
        this.onPartial = onPartial || null;
        this.locale = voiceLangToLocale(lang);
        this.active = true;
        const ok = this.spawn();
        if (!ok)
            this.active = false;
        return ok;
    }
    /**
     * Start one recognizer session.
     *
     * `continuous = true` is not enough on Chrome: the session still ends after a
     * stretch of silence. Without respawning, a pause mid-sentence would freeze
     * the live preview for the rest of the recording.
     */
    spawn() {
        const Ctor = getSpeechRecognitionCtor();
        if (!Ctor)
            return false;
        const rec = new Ctor();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = this.locale;
        rec.onresult = (event) => {
            let full = "";
            for (let i = 0; i < event.results.length; i += 1) {
                full += event.results[i]?.[0]?.transcript || "";
            }
            this.sessionText = full;
            this.failedSessions = 0;
            if (this.onPartial)
                this.onPartial(this.text);
        };
        rec.onerror = () => {
            /* browser STT is best-effort only; onend decides whether to respawn */
        };
        rec.onend = () => {
            const wasFast = Date.now() - this.sessionStartedAt < _FAILED_SESSION_MS;
            if (wasFast && !this.sessionText)
                this.failedSessions += 1;
            this.committed += this.sessionText;
            this.sessionText = "";
            this.recognition = null;
            // Bail out instead of spinning when the recognizer service is unreachable.
            if (this.active && this.failedSessions < _MAX_FAILED_SESSIONS)
                this.spawn();
        };
        try {
            this.sessionStartedAt = Date.now();
            rec.start();
            this.recognition = rec;
            return true;
        }
        catch {
            this.recognition = null;
            return false;
        }
    }
    /** True once the recognizer has produced any text this recording. */
    hasText() {
        return this.text.length > 0;
    }
    stop() {
        this.active = false;
        this.onPartial = null;
        const text = this.text;
        if (this.recognition) {
            try {
                this.recognition.stop();
            }
            catch {
                /* ignore */
            }
            this.recognition = null;
        }
        this.committed = "";
        this.sessionText = "";
        return text;
    }
}
