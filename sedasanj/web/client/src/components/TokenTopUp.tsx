import { useEffect, useRef, useState } from "react";
import { fmt, request } from "../api";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import OrderPaymentPanel from "./OrderPaymentPanel";

interface TokenPackage { id: string; name: string; tokens: number; price_toman: number }

/** Buy extra LLM tokens; they are used after the plan's monthly tokens run out. */
export default function TokenTopUp({ onError, embedded = false }: { onError: (message: string | null) => void; embedded?: boolean }) {
  const [packages, setPackages] = useState<TokenPackage[] | null>(null);
  const [order, setOrder] = useState<{ id: string; amount: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const keys = useRef<Record<string, string>>({});

  useEffect(() => {
    request<TokenPackage[]>("/v1/billing/token-packages").then(setPackages).catch(() => setPackages([]));
  }, []);

  async function buy(pack: TokenPackage) {
    if (busy) return;
    setBusy(pack.id);
    onError(null);
    try {
      keys.current[pack.id] ??= crypto.randomUUID();
      const created = await request<{ id: string; amount_toman: number }>("/v1/billing/token-orders", {
        method: "POST",
        headers: { "Idempotency-Key": keys.current[pack.id] },
        body: { package_id: pack.id },
      });
      setOrder({ id: created.id, amount: created.amount_toman });
    } catch (reason) {
      const error = reason as { code?: string; message?: string };
      onError(billingErrorMessage(error.code, error.message, "ثبت سفارش بسته توکن انجام نشد؛ دوباره تلاش کنید."));
    } finally {
      setBusy(null);
    }
  }

  if (!packages) return embedded ? <div className="text-sm text-slate-500">در حال دریافت بسته‌ها…</div> : null;
  if (packages.length === 0) {
    return embedded ? (
      <div className="pay-empty" role="status">
        <div className="pay-empty-body">
          <strong>بستهٔ توکن فعال نیست</strong>
          <p>در حال حاضر بستهٔ توکنی برای خرید تعریف نشده است. برای افزایش توکن پلن را ارتقا دهید یا با پشتیبانی تماس بگیرید.</p>
          <div className="pay-empty-actions"><a className="btn-ghost" href="/contact">تماس با پشتیبانی</a></div>
        </div>
      </div>
    ) : null;
  }
  const body = (
    <>
      <p className="section-hint">پس از تمام‌شدن توکن ماهانه پلن، از توکن بسته‌ها مصرف می‌شود. توکن بسته منقضی نمی‌شود.</p>
      {order ? (
        <OrderPaymentPanel orderId={order.id} amountToman={order.amount} title="پرداخت بسته توکن" onClose={() => setOrder(null)} onError={onError} />
      ) : (
        <div className="topup-packages" role="group" aria-label="بستهٔ توکن">
          {packages.map((pack) => (
            <button key={pack.id} type="button" className="topup-package" disabled={busy !== null} onClick={() => void buy(pack)}>
              <strong>{pack.name}</strong>
              <span>{fmt.int(pack.tokens)} توکن</span>
              <span>{fmt.toman(pack.price_toman)}</span>
              <small className="topup-package-cta">{busy === pack.id ? "در حال ثبت سفارش…" : "خرید و پرداخت"}</small>
            </button>
          ))}
        </div>
      )}
    </>
  );
  if (embedded) return <div className="topup">{body}</div>;
  return (
    <div className="card">
      <h2 className="font-bold">خرید بسته توکن هوش مصنوعی</h2>
      {body}
    </div>
  );
}
