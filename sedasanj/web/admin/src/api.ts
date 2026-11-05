// Session storage model (WSTG-SESS-04): the refresh token lives only in an HttpOnly cookie that
// scripts cannot read, and the access token only in this module's memory. localStorage keeps a
// non-secret hint, plus the pre-cookie token keys that are read once to migrate sessions.
const SESSION_HINT_KEY = "cbi.admin.session";
const LEGACY_ACCESS_KEY = "cbi.admin.access";
const LEGACY_REFRESH_KEY = "cbi.admin.refresh";
const TRANSPORT_HEADERS = { "X-Auth-Transport": "cookie" };

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the session then lasts until the tab reloads */
  }
}

let accessToken: string | null = null;
const integerFormat = new Intl.NumberFormat("fa-IR");

function toPersianDigits(value: string | number): string {
  return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

function toLatinDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export const tokens = {
  access: () => accessToken,
  /** True when a refresh cookie (or a pre-cookie stored token) may exist. */
  hasSession: () => readStorage(SESSION_HINT_KEY) === "1" || readStorage(LEGACY_REFRESH_KEY) !== null,
  save(pair: TokenPair) {
    accessToken = pair.access_token;
    writeStorage(SESSION_HINT_KEY, "1");
    writeStorage(LEGACY_ACCESS_KEY, null);
    writeStorage(LEGACY_REFRESH_KEY, null);
  },
  clear() {
    accessToken = null;
    writeStorage(SESSION_HINT_KEY, null);
    writeStorage(LEGACY_ACCESS_KEY, null);
    writeStorage(LEGACY_REFRESH_KEY, null);
  },
};

async function parseError(response: Response): Promise<ApiError> {
  let code = "internal";
  let message = response.statusText;
  try {
    const body = await response.json();
    code = body?.error?.code ?? code;
    message = body?.error?.message ?? message;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(response.status, code, message);
}

let refreshInFlight: Promise<boolean> | null = null;

async function doRefresh(url: string): Promise<boolean> {
  if (!tokens.hasSession()) return false;
  // One-time migration of a pre-cookie session: the old token is sent once in the body and the
  // server answers by setting the cookie; save() then deletes the old keys.
  const legacy = readStorage(LEGACY_REFRESH_KEY);
  const send = () => fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...TRANSPORT_HEADERS },
    body: JSON.stringify({ refresh_token: legacy ?? "" }),
  });
  let response = await send();
  if (response.status === 401 && !legacy) {
    // Another tab may have rotated the cookie a moment ago; retry once with the fresh one.
    await new Promise((resolve) => setTimeout(resolve, 400));
    response = await send();
  }
  if (response.status === 401 || response.status === 403) {
    tokens.clear();
    return false;
  }
  if (!response.ok) return false;
  tokens.save((await response.json()) as TokenPair);
  return true;
}

export async function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = doRefresh("/v1/admin/auth/refresh").finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; retry?: boolean; headers?: Record<string, string>; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = "GET", body, retry = true } = options;
  const headers: Record<string, string> = { ...TRANSPORT_HEADERS, ...(options.headers ?? {}) };
  const access = tokens.access();
  if (access) headers.Authorization = `Bearer ${access}`;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? body as FormData : JSON.stringify(body),
    signal: options.signal,
  });
  if (response.status === 401 && retry && (await refreshSession())) {
    return request<T>(path, { ...options, retry: false });
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const fmt = {
  digits: toPersianDigits,
  latinDigits: toLatinDigits,
  int: (value: number) => integerFormat.format(Math.round(value)),
  toman: (value: number) => `${integerFormat.format(Math.round(value))} تومان`,
  minutes: (seconds: number) =>
    `${integerFormat.format(Math.round(seconds / 60))} دقیقه`,
  dateTime: (iso: string) =>
    new Date(iso).toLocaleString("fa-IR-u-ca-persian", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: "Asia/Tehran",
    }),
  date: (iso: string) =>
    new Date(iso).toLocaleDateString("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran" }),
};

const ERROR_CODES: Record<string, string> = {
  asr_provider_credit:
    "اعتبار حساب سرویس VoiceSanj تمام شده است. حساب را شارژ کنید و کار را دوباره اجرا کنید.",
  llm_provider_credit:
    "اعتبار حساب سرویس VoiceSanj تمام شده است. حساب را شارژ کنید و کار را دوباره اجرا کنید.",
  asr_provider_auth: "کلید API پیاده‌سازی گفتار نامعتبر است.",
  llm_provider_auth: "کلید API تحلیل متن نامعتبر است.",
  asr_provider_rate: "سرویس پیاده‌سازی گفتار موقتاً شلوغ است.",
  llm_provider_rate: "سرویس تحلیل متن موقتاً شلوغ است.",
  asr_provider_model:
    "مدل پیاده‌سازی صوت نامعتبر است. یک مدل ASR نصب‌شده در VoiceSanj انتخاب کنید.",
  llm_provider_request:
    "پارامترهای درخواست تحلیل متن با قرارداد VoiceSanj سازگار نیستند.",
  llm_provider_timeout:
    "پاسخ سرویس تحلیل متن در زمان مقرر آماده نشد و دوباره تلاش می‌شود.",
  llm_provider_first_token_timeout:
    "سرویس تحلیل متن در مهلت مقرر تولید پاسخ را شروع نکرد و دوباره تلاش می‌شود.",
  llm_provider_stream_timeout:
    "جریان پاسخ سرویس تحلیل متن پس از شروع متوقف شد و دوباره تلاش می‌شود.",
  llm_provider_unavailable:
    "ارتباط با سرویس تحلیل متن موقتاً برقرار نشد و دوباره تلاش می‌شود.",
  asr_empty_transcript:
    "پیاده‌سازی گفتار متنی برنگرداند. فایل صوتی و وضعیت سرویس VoiceSanj را بررسی کنید.",
  asr_failed: "خطا در پیاده‌سازی گفتار",
  asr_preprocessing_failed:
    "حذف نویز یا بهبود کیفیت صوت ناموفق بود. تنظیمات پیش‌پردازش را بررسی کنید.",
  llm_failed: "خطا در تحلیل متن",
  notify_failed: "خطا در اطلاع‌رسانی",
};

export function formatJobError(code: string | null, detail: string | null): string {
  if (!code && !detail) return "—";
  const blob = `${code ?? ""} ${detail ?? ""}`;
  if (/insufficient|quota|credit|402|اعتبار VoiceSanj|اعتبار حساب/i.test(blob)) {
    return ERROR_CODES.asr_provider_credit;
  }
  if (/empty text|empty transcript/i.test(blob)) {
    return ERROR_CODES.asr_empty_transcript;
  }
  if (code && ERROR_CODES[code]) {
    return ERROR_CODES[code];
  }
  if (detail && /[\u0600-\u06FF]/.test(detail)) return detail;
  if (detail) return detail;
  return code ?? "—";
}

/** Multipart upload with progress; fetch cannot report upload progress for large zips. */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress: (fraction: number) => void,
  retry = true,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    const access = tokens.access();
    if (access) xhr.setRequestHeader("Authorization", `Bearer ${access}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "ارتباط با سرور برقرار نشد."));
    xhr.onload = async () => {
      if (xhr.status === 401 && retry && (await refreshSession())) {
        uploadWithProgress<T>(path, form, onProgress, false).then(resolve, reject);
        return;
      }
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        /* non-JSON body */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as T);
        return;
      }
      const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
      reject(new ApiError(xhr.status, error?.code ?? "internal", error?.message ?? xhr.statusText));
    };
    xhr.send(form);
  });
}
