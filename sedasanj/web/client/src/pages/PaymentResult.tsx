import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import successArt from "../assets/payments/payment-success.svg";
import failedArt from "../assets/payments/payment-failed.svg";
import pendingArt from "../assets/payments/payment-pending.svg";

interface PaymentStatus {
  order_id: string;
  number: string;
  kind: string;
  status: string;
  amount_toman: number;
  credit_minutes: number;
  payment: {
    gateway_label: string;
    status: string;
    ref_id: string | null;
    card_pan: string | null;
    failure_code: string | null;
  } | null;
}

type Outcome = "paid" | "pending" | "canceled" | "failed";

const COPY: Record<Outcome, { title: string; body: string; art: string }> = {
  paid: { title: "پرداخت با موفقیت ثبت شد", body: "اشتراک یا اعتبار خریداری‌شده اکنون فعال است.", art: successArt },
  pending: { title: "پرداخت در حال تأیید است", body: "تأیید نهایی از بانک چند لحظه طول می‌کشد. این صفحه خودکار به‌روز می‌شود؛ اگر مبلغ از حساب شما کسر شده، نیازی به پرداخت دوباره نیست.", art: pendingArt },
  canceled: { title: "پرداخت لغو شد", body: "مبلغی از حساب شما کسر نشده است. می‌توانید از صفحه حساب، سفارش را دوباره پرداخت کنید.", art: failedArt },
  failed: { title: "پرداخت تکمیل نشد", body: "اگر مبلغ از حساب شما کسر شده، طی چند ساعت توسط بانک برگشت داده می‌شود. می‌توانید دوباره تلاش کنید یا روش پرداخت دیگری را انتخاب کنید.", art: failedArt },
};

function outcomeOf(status: string | null, server: PaymentStatus | null): Outcome {
  if (server) {
    if (["paid", "partially_refunded", "refunded"].includes(server.status)) return "paid";
    if (server.payment?.status === "pending_verification") return "pending";
    if (server.payment?.status === "canceled") return "canceled";
    if (status === "pending" && server.payment?.status === "redirected") return "pending";
    return status === "canceled" ? "canceled" : "failed";
  }
  // "superseded": another attempt already paid this order.
  if (status === "superseded") return "paid";
  return status === "paid" || status === "pending" || status === "canceled" ? (status as Outcome) : "failed";
}

export default function PaymentResult() {
  const [params] = useSearchParams();
  const orderId = params.get("order");
  const [server, setServer] = useState<PaymentStatus | null>(null);
  const [tries, setTries] = useState(0);
  const outcome = outcomeOf(params.get("status"), server);

  useEffect(() => {
    if (!orderId) return;
    let alive = true;
    request<PaymentStatus>(`/v1/orders/${orderId}/payment-status`)
      .then((value) => alive && setServer(value))
      .catch(() => undefined); // the redirect status in the URL is shown instead
    return () => {
      alive = false;
    };
  }, [orderId, tries]);

  useEffect(() => {
    if (outcome !== "pending" || tries >= 20) return;
    const timer = window.setTimeout(() => setTries((value) => value + 1), 6000);
    return () => window.clearTimeout(timer);
  }, [outcome, tries]);

  const copy = COPY[outcome];
  return (
    <div className="card mx-auto max-w-xl p-10 text-center" aria-live="polite">
      <img className="mx-auto mb-4" src={copy.art} alt="" width={240} height={165} />
      <h1 className="text-2xl font-bold">{copy.title}</h1>
      <p className="mt-3 text-sm text-slate-500">{copy.body}</p>
      {server ? (
        <dl className="pay-receipt">
          <div><dt>شماره سفارش</dt><dd dir="ltr">{server.number}</dd></div>
          <div><dt>مبلغ</dt><dd>{fmt.toman(server.amount_toman)}</dd></div>
          {server.credit_minutes ? <div><dt>اعتبار خریداری‌شده</dt><dd>{fmt.minutes(server.credit_minutes * 60)}</dd></div> : null}
          {server.payment ? <div><dt>درگاه</dt><dd>{server.payment.gateway_label}</dd></div> : null}
          {outcome === "paid" && server.payment?.ref_id ? <div><dt>شماره پیگیری</dt><dd dir="ltr">{server.payment.ref_id}</dd></div> : null}
          {outcome === "paid" && server.payment?.card_pan ? <div><dt>کارت پرداخت‌کننده</dt><dd dir="ltr">{server.payment.card_pan}</dd></div> : null}
        </dl>
      ) : null}
      <Link className="btn mt-6 inline-flex" to="/account">بازگشت به حساب</Link>
    </div>
  );
}
