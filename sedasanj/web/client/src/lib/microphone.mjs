// Shared microphone helpers. Pure functions take their inputs explicitly so they can be unit tested without a browser.

const EMBEDDED_BROWSER = /FBAN|FBAV|FB_IAB|Instagram|Telegram|Line\/|Snapchat|Twitter|MicroMessenger|Bale|Eitaa|Rubika|Soroush|iGap|; wv\)|\bwv\b/i;

export function isEmbeddedBrowser(userAgent) {
  return EMBEDDED_BROWSER.test(userAgent || "");
}

export function microphoneSupportIssue({ isSecureContext, policy, hasGetUserMedia, hasMediaRecorder }) {
  if (!isSecureContext) return "insecure";
  if (policy?.allowsFeature?.("microphone") === false) return "policy";
  if (!hasGetUserMedia || !hasMediaRecorder) return "unsupported";
  return null;
}

export function classifyMicrophoneError(error) {
  const name = error && typeof error === "object" ? error.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "DevicesNotFoundError") return "no_device";
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "busy";
  if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") return "constraints";
  if (name === "InvalidStateError") return "inactive";
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

export const quickDemoMicrophoneIssues = {
  insecure: { code: "quick_demo_mic_insecure", message: "لینک تست را با HTTPS باز کنید یا از صفحه اصلی یک لینک امن جدید بگیرید." },
  policy: { code: "quick_demo_mic_policy", message: "سیاست امنیتی صفحه دسترسی میکروفون را بسته است. لینک تست را مستقیماً در Safari یا Chrome باز کنید." },
  unsupported: { code: "quick_demo_mic_unsupported", message: "ضبط صدا در این مرورگر در دسترس نیست. لینک تست را در Safari یا Chrome به‌روز باز کنید." },
  denied: { code: "quick_demo_mic_denied", message: "در تنظیمات همین سایت، میکروفون را روی «اجازه» یا «پرسیدن» بگذارید. دسترسی میکروفون مرورگر را هم در تنظیمات دستگاه بررسی کنید و دوباره شروع کنید." },
  no_device: { code: "quick_demo_mic_missing", message: microphoneErrorMessage("no_device") },
  busy: { code: "quick_demo_mic_unreadable", message: "میکروفون باز نشد. تماس یا برنامهٔ ضبط دیگر را ببندید، اتصال میکروفون را بررسی کنید و دوباره شروع کنید." },
  inactive: { code: "quick_demo_mic_inactive", message: "به زبانهٔ تست برگردید و دوباره دکمهٔ شروع را بزنید." },
  constraints: { code: "quick_demo_mic_constraints", message: "ورودی صدای سازگار پیدا نشد. میکروفون پیش‌فرض را بررسی کنید و دوباره شروع کنید." },
  unknown: { code: "quick_demo_mic_failed", message: microphoneErrorMessage("unknown") },
  pending: { code: "quick_demo_mic_pending", message: "مرورگر هنوز پاسخ نداده است. اعلان یا آیکن میکروفون کنار نوار آدرس را بررسی کنید. برای بررسی تنظیمات یا امتحان دوباره، به مرحلهٔ شروع برگردید." },
};

export function speechErrorMessage(code, { embedded = false } = {}) {
  if (code === "not-allowed" || code === "service-not-allowed") return microphoneErrorMessage("denied", { embedded });
  if (code === "audio-capture") return microphoneErrorMessage("no_device");
  if (code === "network") return "تبدیل گفتار به اینترنت نیاز دارد؛ اتصال را بررسی کنید.";
  if (code === "language-not-supported") return "این مرورگر گفتار فارسی را پشتیبانی نمی‌کند؛ از Chrome استفاده کنید.";
  return "";
}

// Call from the start button before waiting for any other work.
export function requestMicrophone(mediaDevices) {
  return mediaDevices.getUserMedia({ audio: true });
}
