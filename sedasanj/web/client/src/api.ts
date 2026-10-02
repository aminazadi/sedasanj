import type { TokenPair } from "./types";

const integerFormat = new Intl.NumberFormat("fa-IR");
const twoDigitFormat = new Intl.NumberFormat("fa-IR", {
  minimumIntegerDigits: 2,
  useGrouping: false,
});

function toPersianDigits(value: string | number): string {
  return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

function toLatinDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

const ACCESS_KEY = "cbi.access";
const REFRESH_KEY = "cbi.refresh";

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

async function doRefresh(): Promise<boolean> {
  const refresh = tokens.refresh();
  if (!refresh) return false;
  const response = await fetch("/v1/auth/refresh", {
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
  refreshInFlight = doRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  retry?: boolean;
  raw?: boolean;
  headers?: Record<string, string>;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, retry = true, raw = false } = options;
  const headers: Record<string, string> = { ...options.headers };
  const access = tokens.access();
  if (access) headers.Authorization = `Bearer ${access}`;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    redirect: raw ? "manual" : "follow",
  });

  if (response.status === 401 && retry && (await refreshSession())) {
    return request<T>(path, { ...options, retry: false });
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const fmt = {
  digits: toPersianDigits,
  latinDigits: toLatinDigits,
  int: (value: number) => integerFormat.format(Math.round(value)),
  decimal: (value: number, maximumFractionDigits = 1) =>
    new Intl.NumberFormat("fa-IR", { maximumFractionDigits }).format(value),
  toman: (value: number) => `${integerFormat.format(Math.round(value))} تومان`,
  minutes: (seconds: number) => `${integerFormat.format(Math.round(seconds / 60))} دقیقه`,
  duration: (ms: number) => {
    const total = Math.round(ms / 1000);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${integerFormat.format(minutes)}:${twoDigitFormat.format(seconds)}`;
  },
  dateTime: (iso: string) =>
    new Date(iso).toLocaleString("fa-IR-u-ca-persian", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: "Asia/Tehran",
    }),
  time: (iso: string) =>
    new Date(iso).toLocaleTimeString("fa-IR", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Tehran",
    }),
  date: (iso: string) =>
    new Date(iso).toLocaleDateString("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran" }),
  calendarDate: (value: string) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    if (!match) {
      return new Date(value).toLocaleDateString("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran" });
    }
    const utc = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
    return utc.toLocaleDateString("fa-IR-u-ca-persian", { timeZone: "UTC" });
  },
  percent: (value: number) => `${integerFormat.format(Math.round(value))}٪`,
};

export const STATUS_LABELS: Record<string, string> = {
  received: "دریافت‌شده",
  reserved: "رزرو اعتبار",
  stored: "ذخیره‌شده",
  transcribing: "در حال پیاده‌سازی",
  transcribed: "پیاده‌سازی شد",
  correcting: "در حال تصحیح متن",
  emotion_queued: "در صف تحلیل لحن",
  emotion_analyzing: "در حال تحلیل لحن",
  analyzing: "در حال تحلیل",
  analyzed: "تحلیل شد",
  billed: "محاسبه شد",
  notified: "اطلاع‌رسانی شد",
  complete: "کامل",
  failed_retryable: "خطای موقت",
  failed_terminal: "خطای نهایی",
  canceled: "لغو شده",
};

export const SENTIMENT_LABELS: Record<string, string> = {
  angry: "عصبانی",
  sad: "ناراحت",
  neutral: "خنثی",
  satisfied: "راضی",
  happy: "خوشحال",
};

export const TRAJECTORY_LABELS: Record<string, string> = {
  improved: "بهبود",
  worsened: "افت",
  stable: "ثابت",
};

export const INTENT_LABELS: Record<string, string> = {
  technical_support: "پشتیبانی فنی",
  sales_inquiry: "استعلام فروش",
  complaint: "شکایت",
  consultation: "مشاوره",
  billing: "امور مالی",
  other: "سایر",
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  open: "انجام نشده",
  done: "انجام شده",
};

export const TASK_PRIORITY_LABELS: Record<string, string> = {
  high: "بالا",
  normal: "معمولی",
  low: "پایین",
};
