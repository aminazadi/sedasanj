import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { GATEWAY_LOGOS, type GatewayCode, type PaymentMethod } from "../lib/payment";
import secureArt from "../assets/payments/secure-payment.svg";

interface Props {
  amountToman?: number;
  value: GatewayCode | null;
  onChange: (code: GatewayCode | null) => void;
  /** Reports whether any payment method can currently be used. */
  onAvailability?: (available: boolean) => void;
}

/** Radio cards for the enabled payment gateways only (the server hides disabled ones). */
export default function PaymentMethodPicker({ amountToman, value, onChange, onAvailability }: Props) {
  const [methods, setMethods] = useState<PaymentMethod[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const query = amountToman && amountToman > 0 ? `?amount_toman=${amountToman}` : "";
    let alive = true;
    request<PaymentMethod[]>(`/v1/billing/payment-methods${query}`)
      .then((list) => {
        if (alive) setMethods(list);
      })
      .catch((reason) => alive && setError((reason as Error).message));
    return () => {
      alive = false;
    };
  }, [amountToman]);

  useEffect(() => {
    if (!methods) return;
    const usable = methods.filter((method) => method.available);
    onAvailability?.(usable.length > 0);
    if (!usable.some((method) => method.code === value)) onChange(usable[0]?.code ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [methods]);

  if (error) return <div className="commerce-error">{error}</div>;
  if (!methods) return <div className="text-sm text-slate-500">در حال دریافت روش‌های پرداخت…</div>;
  if (methods.length === 0) {
    return (
      <div className="pay-empty" role="alert">
        <img src={secureArt} alt="" width={96} height={60} />
        <p>در حال حاضر هیچ درگاه پرداختی فعال نیست. لطفاً با پشتیبانی تماس بگیرید.</p>
      </div>
    );
  }
  return (
    <fieldset className="pay-methods">
      <legend className="pay-legend">روش پرداخت</legend>
      {methods.map((method) => {
        const selected = value === method.code;
        return (
          <label
            key={method.code}
            className={`pay-method${selected ? " is-selected" : ""}${method.available ? "" : " is-disabled"}`}
          >
            <input
              type="radio"
              name="payment-method"
              value={method.code}
              checked={selected}
              disabled={!method.available}
              onChange={() => onChange(method.code)}
            />
            <img src={GATEWAY_LOGOS[method.code]} alt="" width={44} height={44} loading="lazy" />
            <span className="pay-method-text">
              <strong>{method.name}</strong>
              <small>
                {method.available
                  ? method.description
                  : `برای این مبلغ در دسترس نیست (حداقل ${fmt.toman(method.min_toman)}${
                      method.max_toman ? `، حداکثر ${fmt.toman(method.max_toman)}` : ""
                    })`}
              </small>
            </span>
            {method.sandbox ? <em className="pay-badge">آزمایشی</em> : null}
          </label>
        );
      })}
    </fieldset>
  );
}
