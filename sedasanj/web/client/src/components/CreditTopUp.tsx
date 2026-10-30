import { useEffect, useRef, useState } from "react";
import { fmt, request } from "../api";
import { startPayment, type GatewayCode } from "../lib/payment";
import PaymentMethodPicker from "./PaymentMethodPicker";
import { Empty } from "./Widgets";
import type { Package } from "../types";

interface Quote {
  minutes: number;
  price_per_minute_toman: number;
  total_toman: number;
}

const PRESETS = [60, 300, 1000, 3000];
const MIN_MINUTES = 10;
const MAX_MINUTES = 1_000_000;

interface Props {
  packages: Package[];
  pricePerMinute: number;
  onError: (message: string | null) => void;
}

/** Credit purchase: ready packages or any number of minutes at the current per-minute tariff. */
export default function CreditTopUp({ packages, pricePerMinute, onError }: Props) {
  const [mode, setMode] = useState<"custom" | "package">("custom");
  const [minutes, setMinutes] = useState(300);
  const [packageId, setPackageId] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [gateway, setGateway] = useState<GatewayCode | null>(null);
  const [anyMethod, setAnyMethod] = useState(true);
  const [busy, setBusy] = useState(false);
  // One order per distinct purchase: retrying after an error reuses it instead of piling up drafts.
  const orderKey = useRef<{ signature: string; key: string } | null>(null);

  useEffect(() => {
    // Coming back from the bank with the back button restores this page with busy still set.
    const reset = (event: PageTransitionEvent) => event.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  const selectedPackage = packages.find((item) => item.id === packageId) ?? null;
  const valid = minutes >= MIN_MINUTES && minutes <= MAX_MINUTES;

  useEffect(() => {
    if (mode !== "custom" || !valid) {
      setQuote(null);
      return;
    }
    let alive = true;
    const timer = window.setTimeout(() => {
      request<Quote>(`/v1/billing/credit-quote?minutes=${minutes}`)
        .then((result) => alive && setQuote(result))
        .catch((reason) => alive && onError((reason as Error).message));
    }, 250);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [mode, minutes, valid]);

  const quoted = quote && quote.minutes === minutes ? quote : null;
  const total = mode === "custom" ? (quoted?.total_toman ?? minutes * pricePerMinute) : (selectedPackage?.price_toman ?? 0);
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
      onError((reason as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="topup">
      <div className="period-switch" role="tablist" aria-label="نوع خرید اعتبار">
        <button type="button" role="tab" aria-selected={mode === "custom"} className={mode === "custom" ? "active" : ""} onClick={() => setMode("custom")}>تعداد دلخواه دقیقه</button>
        <button type="button" role="tab" aria-selected={mode === "package"} className={mode === "package" ? "active" : ""} onClick={() => setMode("package")}>بسته‌های آماده</button>
      </div>

      {mode === "custom" ? (
        <div className="topup-custom">
          <label className="label" htmlFor="topup-minutes">تعداد دقیقه (حداقل {fmt.int(MIN_MINUTES)})</label>
          <input
            id="topup-minutes"
            className="input"
            inputMode="numeric"
            dir="ltr"
            value={fmt.digits(minutes)}
            onChange={(event) => setMinutes(Number(fmt.latinDigits(event.target.value).replace(/\D/g, "")) || 0)}
          />
          <div className="topup-presets">
            {PRESETS.map((preset) => (
              <button key={preset} type="button" className={minutes === preset ? "btn" : "btn-ghost"} onClick={() => setMinutes(preset)}>
                {fmt.int(preset)} دقیقه
              </button>
            ))}
          </div>
          {!valid ? <p className="field-hint">تعداد دقیقه باید بین {fmt.int(MIN_MINUTES)} و {fmt.int(MAX_MINUTES)} باشد.</p> : null}
          <dl className="topup-summary">
            <div><dt>نرخ هر دقیقه</dt><dd>{fmt.toman(quoted?.price_per_minute_toman ?? pricePerMinute)}</dd></div>
            <div><dt>دقیقه‌های خریداری‌شده</dt><dd>{valid ? fmt.minutes(minutes * 60) : "—"}</dd></div>
          </dl>
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
              <span>{fmt.int(item.minutes)} دقیقه</span>
              <span>{fmt.toman(item.price_toman)}</span>
            </button>
          ))}
        </div>
      )}

      <PaymentMethodPicker amountToman={total} value={gateway} onChange={setGateway} onAvailability={setAnyMethod} />

      <div className="topup-total">
        <span>مبلغ قابل پرداخت</span>
        <strong>{fmt.toman(total)}</strong>
      </div>
      <button type="button" className="btn w-full" disabled={!ready || busy} onClick={() => void pay()}>
        {busy ? "در حال انتقال به درگاه…" : "پرداخت و شارژ اعتبار"}
      </button>
    </div>
  );
}
