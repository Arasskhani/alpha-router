export type CaptureRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DisplayFit = {
  offsetX: number;
  offsetY: number;
  drawWidth: number;
  drawHeight: number;
};

export type ScreenshotFrame = {
  objectUrl: string;
  width: number;
  height: number;
};

export const MIN_CROP_PX = 16;

export function normalizeDragRect(
  a: { x: number; y: number },
  b: { x: number; y: number },
): CaptureRect {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y) };
}

export function containFit(
  imageWidth: number,
  imageHeight: number,
  boxWidth: number,
  boxHeight: number,
): DisplayFit {
  if (imageWidth <= 0 || imageHeight <= 0 || boxWidth <= 0 || boxHeight <= 0) {
    return { offsetX: 0, offsetY: 0, drawWidth: 0, drawHeight: 0 };
  }
  const scale = Math.min(boxWidth / imageWidth, boxHeight / imageHeight);
  const drawWidth = imageWidth * scale;
  const drawHeight = imageHeight * scale;
  return {
    offsetX: (boxWidth - drawWidth) / 2,
    offsetY: (boxHeight - drawHeight) / 2,
    drawWidth,
    drawHeight,
  };
}

export function mapDisplayedRectToImage(
  displayRect: CaptureRect,
  fit: DisplayFit,
  imageWidth: number,
  imageHeight: number,
): CaptureRect | null {
  if (fit.drawWidth <= 0 || fit.drawHeight <= 0 || imageWidth <= 0 || imageHeight <= 0) {
    return null;
  }
  const scaleX = imageWidth / fit.drawWidth;
  const scaleY = imageHeight / fit.drawHeight;
  let x = (displayRect.x - fit.offsetX) * scaleX;
  let y = (displayRect.y - fit.offsetY) * scaleY;
  let width = displayRect.width * scaleX;
  let height = displayRect.height * scaleY;
  if (x < 0) {
    width += x;
    x = 0;
  }
  if (y < 0) {
    height += y;
    y = 0;
  }
  if (x + width > imageWidth) width = imageWidth - x;
  if (y + height > imageHeight) height = imageHeight - y;
  if (width < 1 || height < 1) return null;
  return { x, y, width, height };
}

export function isCropLargeEnough(rect: CaptureRect, min = MIN_CROP_PX): boolean {
  return rect.width >= min && rect.height >= min;
}

export function screenshotFileName(at: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `screenshot-${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}.png`;
}

export function revokeScreenshotFrame(frame: ScreenshotFrame | null | undefined): void {
  if (frame?.objectUrl) URL.revokeObjectURL(frame.objectUrl);
}

export function screenshotPermissionErrorMessage(err: unknown): string | null {
  if (!err || typeof err !== "object" || !("name" in err)) return null;
  const name = String((err as { name?: string }).name);
  if (name === "NotAllowedError" || name === "AbortError") {
    return "Screen capture was cancelled or blocked. Use Attach file instead.";
  }
  if (name === "NotFoundError" || name === "NotSupportedError") {
    return "Screen capture is not available in this browser. Use Attach file instead.";
  }
  return null;
}

function stopStream(stream: MediaStream): void {
  for (const track of stream.getTracks()) track.stop();
}

async function waitForVideoFrame(video: HTMLVideoElement): Promise<void> {
  if (video.videoWidth > 0 && video.readyState >= 2) return;
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new Error("Could not read the captured screen.")),
      8000,
    );
    const ok = () => {
      window.clearTimeout(timeout);
      resolve();
    };
    video.addEventListener("loadeddata", ok, { once: true });
    video.addEventListener(
      "error",
      () => {
        window.clearTimeout(timeout);
        reject(new Error("Could not read the captured screen."));
      },
      { once: true },
    );
  });
}

export async function captureDisplayFrame(): Promise<ScreenshotFrame> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error("Screen capture is not available in this browser. Use Attach file instead.");
  }
  const options: DisplayMediaStreamOptions & {
    preferCurrentTab?: boolean;
    selfBrowserSurface?: "include" | "exclude";
  } = {
    video: true,
    audio: false,
    preferCurrentTab: true,
    selfBrowserSurface: "include",
  };
  const stream = await navigator.mediaDevices.getDisplayMedia(options);
  try {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    await waitForVideoFrame(video);
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) {
      throw new Error("Could not read the captured screen.");
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not capture a screenshot frame.");
    ctx.drawImage(video, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (next) => (next ? resolve(next) : reject(new Error("Could not encode the screenshot."))),
        "image/png",
      );
    });
    return { objectUrl: URL.createObjectURL(blob), width, height };
  } finally {
    stopStream(stream);
  }
}

export async function cropScreenshotToFile(
  frame: ScreenshotFrame,
  imageRect: CaptureRect,
  fileName?: string,
): Promise<File> {
  const img = new Image();
  img.src = frame.objectUrl;
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("Could not load the screenshot."));
  });
  const x = Math.max(0, Math.floor(imageRect.x));
  const y = Math.max(0, Math.floor(imageRect.y));
  const width = Math.max(1, Math.min(Math.floor(imageRect.width), img.naturalWidth - x));
  const height = Math.max(1, Math.min(Math.floor(imageRect.height), img.naturalHeight - y));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not crop the screenshot.");
  ctx.drawImage(img, x, y, width, height, 0, 0, width, height);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (next) => (next ? resolve(next) : reject(new Error("Could not encode the screenshot."))),
      "image/png",
    );
  });
  return new File([blob], fileName || screenshotFileName(), { type: "image/png" });
}
