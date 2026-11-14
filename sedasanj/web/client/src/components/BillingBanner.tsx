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
    <div className="billing-banner" role="alert">
      <span className="billing-banner__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          <path d="M12 9v4M12 17h.01" />
        </svg>
      </span>
      <div className="billing-banner__body">
        {messages.map((m) => (
          <p key={m}>{m}</p>
        ))}
      </div>
      <Link className="billing-banner__action" to="/account">رفتن به حساب</Link>
    </div>
  );
}
