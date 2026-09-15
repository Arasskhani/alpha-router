/**
 * Re-encode a recording as 16 kHz mono 16-bit PCM WAV.
 *
 * `MediaRecorder` cannot produce WAV — it gives webm/opus or mp4 — but several
 * transcription models accept nothing else ("requires WAV audio (input is not a
 * RIFF/WAVE container)"). The browser can decode its own recording, so the
 * conversion needs no library, no extra permission and no server round-trip.
 *
 * 16 kHz mono is what speech-to-text models resample to internally, so this
 * costs no accuracy. It does roughly double the upload versus opus, which is a
 * fair trade for "every model works".
 */

/** What STT models use internally; sending anything higher is wasted bytes. */
const TARGET_SAMPLE_RATE = 16000;
const BYTES_PER_SAMPLE = 2;
const WAV_HEADER_BYTES = 44;

export type WavAudio = {
  blob: Blob;
  /** Exact length of the decoded audio — no estimate involved. */
  durationSeconds: number;
  sampleRate: number;
};

type AudioContextCtor = typeof AudioContext;
type OfflineAudioContextCtor = typeof OfflineAudioContext;

function audioContextCtor(): AudioContextCtor | null {
  const w = window as Window & { webkitAudioContext?: AudioContextCtor };
  return window.AudioContext || w.webkitAudioContext || null;
}

function offlineAudioContextCtor(): OfflineAudioContextCtor | null {
  const w = window as Window & { webkitOfflineAudioContext?: OfflineAudioContextCtor };
  return window.OfflineAudioContext || w.webkitOfflineAudioContext || null;
}
/**
 * Downmix to mono at `sampleRate`.
 *
 * Falls back to the source rate when the browser refuses the target one — older
 * WebKit only allowed 44100 in an OfflineAudioContext. A larger WAV still beats
 * a failed conversion.
 */
async function renderMono(
  buffer: AudioBuffer,
  sampleRate: number,
): Promise<{ samples: Float32Array; sampleRate: number }> {
  const Offline = offlineAudioContextCtor();
  if (!Offline) throw new Error("This browser cannot convert audio.");

  const render = async (rate: number) => {
    const frames = Math.max(1, Math.ceil(buffer.duration * rate));
    const offline = new Offline(1, frames, rate);
    const source = offline.createBufferSource();
    source.buffer = buffer;
    source.connect(offline.destination);
    source.start(0);
    const rendered = await offline.startRendering();
    return { samples: rendered.getChannelData(0), sampleRate: rate };
  };

  try {
    return await render(sampleRate);
  } catch {
    return await render(buffer.sampleRate);
  }
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
}

/** Wrap mono float samples in a canonical 16-bit PCM RIFF/WAVE container. */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const dataBytes = samples.length * BYTES_PER_SAMPLE;
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true); // PCM fmt chunk size
  view.setUint16(20, 1, true); // format: PCM
  view.setUint16(22, 1, true); // channels: mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true); // byte rate
  view.setUint16(32, BYTES_PER_SAMPLE, true); // block align
  view.setUint16(34, 8 * BYTES_PER_SAMPLE, true); // bits per sample
  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  let offset = WAV_HEADER_BYTES;
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += BYTES_PER_SAMPLE;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

/** Decode a recorded blob and return it as 16 kHz mono WAV. */
export async function wavFromRecording(blob: Blob): Promise<WavAudio> {
  const Ctx = audioContextCtor();
  if (!Ctx) throw new Error("This browser cannot convert audio.");
  const arrayBuffer = await blob.arrayBuffer();
  if (!arrayBuffer.byteLength) throw new Error("Empty recording.");

  const context = new Ctx();
  let decoded: AudioBuffer;
  try {
    // decodeAudioData detaches the buffer on some engines; hand it a copy.
    decoded = await context.decodeAudioData(arrayBuffer.slice(0));
  } finally {
    void context.close();
  }

  const { samples, sampleRate } = await renderMono(decoded, TARGET_SAMPLE_RATE);
  return {
    blob: encodeWav(samples, sampleRate),
    durationSeconds: samples.length / sampleRate,
    sampleRate,
  };
}
