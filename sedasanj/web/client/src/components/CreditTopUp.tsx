import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import { startPayment, type GatewayCode } from "../lib/payment";
import PaymentMethodPicker from "./PaymentMethodPicker";
import DocumentTabs from "./DocumentTabs";
import { Empty } from "./Widgets";
import { clampMinutes, sliderPosition, stepMinutes } from "../lib/creditUsage.mjs";
import type { Package } from "../types";

interface Quote {
  minutes: number;
  price_per_minute_toman: number;
  total_toman: number;
}

function describe(reason: unknown): string {
  const error = reason instanceof ApiError ? reason : null;
  return billingErrorMessage(error?.code, error?.message, "انجام نشد؛ دوباره تلاش کنید.");
}

interface CreditSettings {
  min_minutes: number;
  max_minutes: number;
  presets: number[];
  tax_percent: number;
}

// Used only until the admin-managed limits arrive from the API.
const DEFAULT_SETTINGS: CreditSettings = { min_minutes: 10, max_minutes: 1_000_000, presets: [60, 300, 1000, 3000], tax_percent: 0 };

interface Props {
  packages: Package[];
  pricePerMinute: number;
  onError: (message: string | null) => void;
}

/** Credit purchase: ready packages or any number of minutes at the current per-minute tariff. */
export default function CreditTopUp({ packages, pricePerMinute, onError }: Props) {
  const [params, setParams] = useSearchParams();
  const mode: "custom" | "package" = params.get("topup") === "package" ? "package" : "custom";
  const setMode = (value: "custom" | "package") => {
    const next = new URLSearchParams(params);
    if (value === "package") next.set("topup", "package");
    else next.delete("topup");
    setParams(next, { replace: true });
  };
  const [minutes, setMinutes] = useState(300);
  const [packageId, setPackageId] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [settings, setSettings] = useState<CreditSettings>(DEFAULT_SETTINGS);
  const [gateway, setGateway] = useState<GatewayCode | null>(null);
  const [anyMethod, setAnyMethod] = useState(true);
  const [busy, setBusy] = useState(false);
  const [taxPercent, setTaxPercent] = useState(0);
  // One order per distinct purchase: retrying after an error reuses it instead of piling up drafts.
  const quoteCache = useRef(new Map<number, Quote>());
  const orderKey = useRef<{ signature: string; key: string } | null>(null);

  useEffect(() => {
    // Coming back from the bank with the back button restores this page with busy still set.
    const reset = (event: PageTransitionEvent) => event.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  useEffect(() => {
    request<CreditSettings>("/v1/billing/credit-settings")
      .then(setSettings)
      .catch(() => undefined);
  }, []);

  const MIN_MINUTES = settings.min_minutes;
  const MAX_MINUTES = settings.max_minutes;
  const selectedPackage = packages.find((item) => item.id === packageId) ?? null;
  const valid = minutes >= MIN_MINUTES && minutes <= MAX_MINUTES;

  useEffect(() => {
    const quoteMinutes = mode === "custom" ? minutes : (selectedPackage?.minutes ?? 0);
    if (mode === "custom" ? !valid : quoteMinutes <= 0) {
      setQuote(null);
      return;
    }
    let alive = true;
    const cached = quoteCache.current.get(quoteMinutes);
    if (cached) {
      setQuote(cached);
      return;
    }
    // Wait until the value stops changing (slider drag, typing) so only the final amount is requested.
    const timer = window.setTimeout(() => {
      request<Quote>(`/v1/billing/credit-quote?minutes=${quoteMinutes}`)
        .then((result) => {
          quoteCache.current.set(quoteMinutes, result);
          if (alive) setQuote(result);
        })
        .catch((reason) => alive && onError(describe(reason)));
    }, 700);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [mode, minutes, valid, packageId, selectedPackage?.minutes]);

  useEffect(() => setTaxPercent(settings.tax_percent), [settings.tax_percent]);

  const quoted = quote && quote.minutes === (mode === "custom" ? minutes : selectedPackage?.minutes) ? quote : null;
  // Package prices come from the plan's per-minute price, never from a separate package price.
  const packageNet = (selectedPackage?.minutes ?? 0) * pricePerMinute;
  const packageTotal = quoted?.total_toman ?? packageNet + Math.floor((packageNet * taxPercent + 50) / 100);
  const total = mode === "custom" ? (quoted?.total_toman ?? minutes * pricePerMinute) : packageTotal;
  // The payment-method list only depends on the amount range, so it follows the amount after it settles.
  const [settledTotal, setSettledTotal] = useState(total);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettledTotal(total), 800);
    return () => window.clearTimeout(timer);
  }, [total]);
  const ready = anyMethod && gateway !== null && total > 0 && (mode === "custom" ? valid : selectedPackage !== null);

  async function pay() {
    if (!ready || busy) return;
    setBusy(true);
    onError(null);
    try {
      const signature = mode === "custom" ? `m:${minutes}` : `p:${packageId}`;
      if (orderKey.current?.signature !== signature) {
        orderKey.current = { signature, key: crypto.randomUUID() };
      }
      const order = await request<{ id: string }>("/v1/billing/credit-orders", {
        method: "POST",
        headers: { "Idempotency-Key": orderKey.current.key },
        body: mode === "custom" ? { minutes } : { package_id: packageId },
      });
      await startPayment(order.id, gateway);
    } catch (reason) {
      onError(describe(reason));
      setBusy(false);
    }
  }

  return (
    <div className="topup">
      <DocumentTabs
        value={mode}
        onChange={setMode}
        label="نوع خرید اعتبار"
        variant="sub"
        options={[
          { value: "custom", label: "تعداد دلخواه دقیقه" },
          { value: "package", label: "بسته‌های آماده" },
        ]}
      />

      {mode === "custom" ? (
        <div className="topup-custom">
          <label className="label" htmlFor="topup-minutes">تعداد دقیقه (حداقل {fmt.int(MIN_MINUTES)})</label>
          <div className="topup-stepper">
            <button type="button" aria-label="کم کردن دقیقه" disabled={minutes <= MIN_MINUTES} onClick={() => setMinutes(stepMinutes(minutes, -1, MIN_MINUTES, MAX_MINUTES))}>−</button>
            <input
              id="topup-minutes"
              className="input"
              inputMode="numeric"
              dir="ltr"
              aria-invalid={!valid}
              value={fmt.digits(minutes)}
              onChange={(event) => setMinutes(Number(fmt.latinDigits(event.target.value).replace(/\D/g, "")) || 0)}
            />
            <span className="topup-unit" aria-hidden="true">دقیقه</span>
            <button type="button" aria-label="اضافه کردن دقیقه" disabled={minutes >= MAX_MINUTES} onClick={() => setMinutes(stepMinutes(minutes, 1, MIN_MINUTES, MAX_MINUTES))}>+</button>
          </div>
          <input
            className="topup-slider"
            type="range"
            dir="ltr"
            min={0}
            max={100}
            step={0.5}
            aria-label="انتخاب سریع تعداد دقیقه"
            value={valid ? sliderPosition(minutes, MIN_MINUTES, MAX_MINUTES) : 0}
            style={{ "--fill": `${valid ? sliderPosition(minutes, MIN_MINUTES, MAX_MINUTES) : 0}%` } as CSSProperties}
            onChange={(event) => {
              const ratio = Number(event.target.value) / 100;
              const raw = Math.exp(Math.log(Math.max(MIN_MINUTES, 1)) + ratio * (Math.log(Math.max(MAX_MINUTES, MIN_MINUTES + 1)) - Math.log(Math.max(MIN_MINUTES, 1))));
              const step = raw >= 1000 ? 100 : raw >= 100 ? 10 : 5;
              setMinutes(clampMinutes(Math.round(raw / step) * step, MIN_MINUTES, MAX_MINUTES));
            }}
          />
          <div className="topup-presets">
            {settings.presets.map((preset) => (
              <button key={preset} type="button" className={`topup-chip${minutes === preset ? " is-selected" : ""}`} aria-pressed={minutes === preset} onClick={() => setMinutes(preset)}>
                {fmt.int(preset)} دقیقه
              </button>
            ))}
          </div>
          {!valid ? <p className="field-hint" role="alert">تعداد دقیقه باید بین {fmt.int(MIN_MINUTES)} و {fmt.int(MAX_MINUTES)} باشد.</p> : null}
        </div>
      ) : packages.length === 0 ? (
        <Empty />
      ) : (
        <div className="topup-packages" role="radiogroup" aria-label="بسته اعتبار">
          {packages.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={packageId === item.id}
              className={`topup-package${packageId === item.id ? " is-selected" : ""}`}
              onClick={() => setPackageId(item.id)}
            >
              <strong>{item.name}</strong>
              {fmt.latinDigits(item.name).includes(String(item.minutes)) ? null : <span>{fmt.minutes(item.minutes * 60)}</span>}
              <span className="topup-package-price">{fmt.toman(item.minutes * pricePerMinute)}</span>
            </button>
          ))}
        </div>
      )}

      <PaymentMethodPicker amountToman={settledTotal} value={gateway} onChange={setGateway} onAvailability={setAnyMethod} />

      <dl className="topup-summary">
        {mode === "custom" ? (
          <>
            <div><dt>مقدار</dt><dd>{valid ? fmt.minutes(minutes * 60) : "—"}</dd></div>
            <div><dt>نرخ هر دقیقه</dt><dd>{fmt.toman(quoted?.price_per_minute_toman ?? pricePerMinute)}</dd></div>
          </>
        ) : (
          <>
            <div><dt>بستهٔ انتخابی</dt><dd>{selectedPackage ? `${selectedPackage.name} · ${fmt.minutes(selectedPackage.minutes * 60)}` : "—"}</dd></div>
            {taxPercent ? <div><dt>مالیات ({fmt.int(taxPercent)}٪)</dt><dd>{fmt.toman(packageTotal - packageNet)}</dd></div> : null}
          </>
        )}
      </dl>
      <div className="topup-total" aria-live="polite">
        <span>مبلغ قابل پرداخت{mode === "package" && taxPercent ? " (با مالیات)" : ""}</span>
        <strong key={total}>{fmt.toman(total)}</strong>
      </div>
      <button type="button" className="btn w-full" disabled={!ready || busy} onClick={() => void pay()}>
        {busy ? "در حال انتقال به درگاه…" : "پرداخت و شارژ اعتبار"}
      </button>
    </div>
  );
}
