const ACCESS_KEY = "cbi.admin.access";
const REFRESH_KEY = "cbi.admin.refresh";
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
  access: () => localStorage.getItem(ACCESS_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  save(pair: TokenPair) {
    localStorage.setItem(ACCESS_KEY, pair.access_token);
    localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
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
  const refresh = tokens.refresh();
  if (!refresh) return false;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
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
  options: { method?: string; body?: unknown; retry?: boolean; headers?: Record<string, string> } = {},
): Promise<T> {
  const { method = "GET", body, retry = true } = options;
  const headers: Record<string, string> = { ...(options.headers ?? {}) };
  const access = tokens.access();
  if (access) headers.Authorization = `Bearer ${access}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
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
