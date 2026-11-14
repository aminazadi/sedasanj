import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import type { Balance, SubscriptionInfo } from "../types";

const LOW_SECONDS = 600;

/** Org-admin banner for the states that stop or are about to stop work: expired, grace, no credit. */
export default function BillingBanner() {
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);

  useEffect(() => {
    request<SubscriptionInfo>("/v1/subscription").then(setSubscription).catch(() => setSubscription(null));
    request<Balance>("/v1/billing/balance").then(setBalance).catch(() => setBalance(null));
  }, []);

  const messages: string[] = [];
  if (subscription) {
    if (subscription.grace_ends_at) {
      messages.push(`اشتراک تمام شده است؛ تا ${fmt.date(subscription.grace_ends_at)} فرصت تمدید دارید.`);
    } else if (["expired", "canceled", "pending_payment"].includes(subscription.status)) {
      messages.push(
        subscription.status === "pending_payment"
          ? "پرداخت اشتراک کامل نشده است؛ پردازش جدید تا تأیید پرداخت شروع نمی‌شود."
          : "اشتراک فعال نیست و پردازش جدید متوقف است.",
      );
    }
    if (!subscription.llm_tokens_unlimited && (subscription.llm_tokens_remaining ?? 1) <= 0) {
      messages.push("توکن هوش مصنوعی این ماه تمام شده است.");
    }
  }
  if (balance && balance.seconds <= 0) messages.push("اعتبار دقیقه تمام شده است؛ تماس‌های جدید پردازش نمی‌شوند.");
  else if (balance && balance.seconds < LOW_SECONDS) {
    messages.push(`اعتبار دقیقه رو به پایان است (${fmt.minutes(balance.seconds)} باقی مانده).`);
  }
  if (messages.length === 0) return null;
  return (
    <div className="mb-5 flex flex-wrap items-center gap-3 border-2 border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
      <span className="font-bold">{messages.join(" ")}</span>
      <Link className="btn-ghost" to="/account">رفتن به حساب</Link>
    </div>
  );
}
