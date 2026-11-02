// Shared microphone helpers. Pure functions take their inputs explicitly so they can be unit tested without a browser.

const EMBEDDED_BROWSER = /FBAN|FBAV|FB_IAB|Instagram|Telegram|Line\/|Snapchat|Twitter|MicroMessenger|Bale|Eitaa|Rubika|Soroush|iGap|; wv\)|\bwv\b/i;

export function isEmbeddedBrowser(userAgent) {
  return EMBEDDED_BROWSER.test(userAgent || "");
}

// Why the page cannot record at all, before any permission prompt is attempted.
export function microphoneSupportIssue({ isSecureContext, hasGetUserMedia, hasMediaRecorder }) {
  if (!isSecureContext) return "insecure";
  if (!hasGetUserMedia || !hasMediaRecorder) return "unsupported";
  return null;
}

export function classifyMicrophoneError(error) {
  const name = error && typeof error === "object" ? error.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "DevicesNotFoundError") return "no_device";
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "busy";
  if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") return "constraints";
  return "unknown";
}

export function microphoneErrorMessage(code, { embedded = false } = {}) {
  if (code === "denied") {
    return embedded
      ? "این مرورگر داخلی اجازهٔ میکروفون نمی‌دهد. لینک را در Safari یا Chrome گوشی باز کنید."
      : "دسترسی میکروفون مسدود است. روی آیکن قفل کنار آدرس بزنید، میکروفون را «اجازه» کنید و دوباره شروع کنید.";
  }
  if (code === "no_device") return "میکروفونی روی این دستگاه پیدا نشد. میکروفون را وصل کنید یا از دستگاه دیگری استفاده کنید.";
  if (code === "busy") return "میکروفون در اختیار برنامهٔ دیگری است. برنامه‌های دیگر (تماس، ضبط صدا) را ببندید و دوباره تلاش کنید.";
  return "میکروفون در دسترس نیست؛ مرورگر یا دستگاه دیگری را امتحان کنید.";
}

export function speechErrorMessage(code, { embedded = false } = {}) {
  if (code === "not-allowed" || code === "service-not-allowed") return microphoneErrorMessage("denied", { embedded });
  if (code === "audio-capture") return microphoneErrorMessage("no_device");
  if (code === "network") return "تبدیل گفتار به اینترنت نیاز دارد؛ اتصال را بررسی کنید.";
  if (code === "language-not-supported") return "این مرورگر گفتار فارسی را پشتیبانی نمی‌کند؛ از Chrome استفاده کنید.";
  return "";
}

// Must be called synchronously from a user gesture (click/tap): Safari and Firefox only show the prompt then.
// A strict constraint failure falls back to plain `{ audio: true }`, so a browser that rejects the
// processing hints still reaches the permission prompt.
export async function requestMicrophone(mediaDevices) {
  try {
    return await mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
  } catch (error) {
    const code = classifyMicrophoneError(error);
    if (code !== "constraints" && !(error instanceof TypeError)) throw error;
    return mediaDevices.getUserMedia({ audio: true });
  }
}
