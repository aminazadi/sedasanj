import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import type { SubscriptionInfo } from "../types";
import CheckoutDialog from "./CheckoutDialog";
import { Icon } from "@iconify/react";
import calendarIcon from "@iconify-icons/lucide/calendar-clock";
import usersIcon from "@iconify-icons/lucide/users";
import clockIcon from "@iconify-icons/lucide/clock";
import messageIcon from "@iconify-icons/lucide/message-square";
import sparklesIcon from "@iconify-icons/lucide/sparkles";
import ConfirmDialog from "./ConfirmDialog";

const STATUS_LABELS: Record<string, string> = {
  active: "فعال",
  trialing: "آزمایشی",
  grace: "در مهلت تمدید",
  pending_payment: "در انتظار پرداخت",
  expired: "منقضی‌شده",
  canceled: "لغوشده",
};

type Action = "cancel" | "resume" | "cancel_change";

const CONFIRM: Record<Action, { title: string; description: string; label: string; destructive: boolean }> = {
  cancel: {
    title: "لغو در پایان دوره",
    description: "اشتراک تا پایان دوره فعلی کار می‌کند و بعد از آن تمدید نمی‌شود. هر زمان تا آن موقع می‌توانید آن را از سر بگیرید.",
    label: "لغو در پایان دوره",
    destructive: true,
  },
  resume: {
    title: "ازسرگیری اشتراک",
    description: "لغو پایان دوره برداشته می‌شود و اشتراک طبق برنامه تمدید می‌شود.",
    label: "ازسرگیری",
    destructive: false,
  },
  cancel_change: {
    title: "لغو تغییر پلن",
    description: "تغییر برنامه‌ریزی‌شده انجام نمی‌شود و پلن فعلی ادامه پیدا می‌کند.",
    label: "لغو تغییر",
    destructive: true,
  },
};

interface Props {
  subscription: SubscriptionInfo;
  onChanged: () => Promise<void> | void;
  onError: (message: string | null) => void;
}

/** The organization's plan with the actions that apply to its current state. */
export default function SubscriptionPanel({ subscription, onChanged, onError }: Props) {
  const [pending, setPending] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [buying, setBuying] = useState(false);
  const status = subscription.grace_ends_at ? "grace" : subscription.status;
  const live = ["active", "trialing", "grace"].includes(status);
  const change = subscription.scheduled_change;
  // Expired, canceled and in-grace organizations must always have a way back to a paid plan.
  const canRenew = ["grace", "expired", "canceled"].includes(status) && !!subscription.plan_code;
  const awaitingPayment = status === "pending_payment";

  async function confirm() {
    if (!pending) return;
    setBusy(true);
    onError(null);
    try {
      if (pending === "cancel") await request("/v1/subscription/cancel-at-period-end", { method: "POST" });
      else if (pending === "resume") await request("/v1/subscription/resume", { method: "POST" });
      else if (change) await request(`/v1/subscription/changes/${change.id}/cancel`, { method: "POST" });
      setPending(null);
      await onChanged();
    } catch (reason) {
      const error = reason instanceof ApiError ? reason : null;
      onError(billingErrorMessage(error?.code, error?.message, "انجام نشد؛ دوباره تلاش کنید."));
      setPending(null);
    } finally {
      setBusy(false);
    }
  }

  const alerts: string[] = [];
  if (subscription.grace_ends_at) alerts.push(`دوره اشتراک تمام شده است؛ تا ${fmt.date(subscription.grace_ends_at)} فرصت دارید تمدید کنید.`);
  if (awaitingPayment) alerts.push("پرداخت اشتراک کامل نشده است؛ در جدول «سفارش‌ها و پرداخت‌ها» پایین همین صفحه روی «پرداخت» بزنید.");
  if (["expired", "canceled"].includes(status)) alerts.push("اشتراک فعال نیست و پردازش جدید متوقف است؛ برای ادامه اشتراک را دوباره بخرید.");
  if (!subscription.llm_tokens_unlimited && (subscription.llm_tokens_remaining ?? 1) <= 0) {
    alerts.push("توکن هوش مصنوعی تمام شده است؛ بسته توکن بخرید یا پلن را ارتقا دهید.");
  }
  const notes: string[] = [];
  if (subscription.cancel_at_period_end) notes.push("لغو شده است و پس از سررسید تمدید نمی‌شود.");
  if (change) {
    notes.push(
      `${change.kind === "downgrade" ? "تنزل" : "ارتقا"} به ${change.target_plan_name ?? change.target_plan_code}${
        change.effective_at ? ` از ${fmt.date(change.effective_at)}` : ""
      } برنامه‌ریزی شده است.`,
    );
  }
  const tokens = subscription.llm_tokens_unlimited
    ? "نامحدود"
    : `${fmt.int(subscription.llm_tokens_used ?? 0)} از ${fmt.int(subscription.llm_tokens_limit ?? 0)}`;
  const used = (value: number | null | undefined, limit: number | null | undefined) => (limit && limit > 0 ? Math.min(100, ((value ?? 0) / limit) * 100) : null);
  const stats: { label: string; value: string; hint?: string; icon: typeof calendarIcon; progress?: number | null }[] = [
    { label: "سررسید", value: subscription.period_end ? fmt.date(subscription.period_end) : "—", icon: calendarIcon },
    { label: "ظرفیت اپراتور", value: `${fmt.int(subscription.max_operators)} نفر`, icon: usersIcon },
    { label: "دقیقه ماهانه پلن", value: `${fmt.int(subscription.plan_monthly_minutes)} دقیقه`, icon: clockIcon },
    {
      label: "پیام دستیار",
      value: `${fmt.int(subscription.assistant_messages_used)} از ${fmt.int(subscription.assistant_monthly_messages)}`,
      hint: `${fmt.int(subscription.assistant_messages_remaining)} باقی‌مانده`,
      icon: messageIcon,
      progress: used(subscription.assistant_messages_used, subscription.assistant_monthly_messages),
    },
    {
      label: "توکن هوش مصنوعی",
      value: tokens,
      hint: subscription.llm_tokens_unlimited
        ? `مصرف این ماه: ${fmt.int(subscription.llm_tokens_used ?? 0)}`
        : `${fmt.int(subscription.llm_tokens_remaining ?? 0)} باقی‌مانده${
            subscription.llm_tokens_topup_remaining ? ` (شامل ${fmt.int(subscription.llm_tokens_topup_remaining)} توکن بسته)` : ""
          }`,
      icon: sparklesIcon,
      progress: subscription.llm_tokens_unlimited ? null : used(subscription.llm_tokens_used, subscription.llm_tokens_limit),
    },
  ];

  return (
    <div className="card sub-card">
      <div className="sub-head">
        <div className="sub-title">
          <h2 className="font-bold">اشتراک سازمان{subscription.plan_name ? ` · ${subscription.plan_name}` : ""}</h2>
          <span className={`sub-chip ${live ? "is-ok" : "is-bad"}`}>{STATUS_LABELS[status] ?? status}</span>
        </div>
        <div className="sub-actions">
          {live && subscription.status === "active" ? <Link className="btn" to="/billing/change-plan">تغییر پلن</Link> : null}
          {canRenew || subscription.status === "trialing" ? (
            <button className="btn" onClick={() => setBuying(true)}>
              {subscription.status === "trialing" ? "خرید پلن" : status === "grace" ? "تمدید اشتراک" : "خرید دوباره اشتراک"}
            </button>
          ) : null}
          {change ? <button className="btn-ghost" onClick={() => setPending("cancel_change")}>لغو تغییر پلن</button> : null}
          {live && !subscription.cancel_at_period_end && subscription.status === "active" ? (
            <button className="btn-ghost" onClick={() => setPending("cancel")}>لغو در پایان دوره</button>
          ) : null}
          {subscription.cancel_at_period_end && live ? <button className="btn-ghost" onClick={() => setPending("resume")}>ازسرگیری</button> : null}
        </div>
      </div>
      {alerts.map((text) => (
        <div key={text} className="billing-banner sub-alert" role="alert">
          <span className="billing-banner__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
              <path d="M12 9v4M12 17h.01" />
            </svg>
          </span>
          <div className="billing-banner__body"><p>{text}</p></div>
        </div>
      ))}
      {notes.map((text) => <p key={text} className="field-hint">{text}</p>)}
      <dl className="sub-stats" data-testid="llm-token-meter">
        {stats.map((item) => (
          <div key={item.label} className="sub-stat">
            <span className="sub-stat__icon" aria-hidden="true"><Icon icon={item.icon} className="h-[18px] w-[18px]" /></span>
            <div className="sub-stat__text">
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
              {item.progress != null ? (
                <span className="sub-stat__bar" role="img" aria-label={`${fmt.int(Math.round(item.progress))}٪ مصرف‌شده`}>
                  <span style={{ width: `${item.progress}%` }} className={item.progress >= 90 ? "is-high" : undefined} />
                </span>
              ) : null}
              {item.hint ? <small>{item.hint}</small> : null}
            </div>
          </div>
        ))}
      </dl>
      <p className="field-hint">مصرف تحلیل گفتار از دقیقه‌های ماهانهٔ پلن کم می‌شود.</p>
      <CheckoutDialog open={buying} initialPlan={subscription.plan_code ?? null} onClose={() => setBuying(false)} />
      {pending ? (
        <ConfirmDialog
          open
          title={CONFIRM[pending].title}
          description={CONFIRM[pending].description}
          confirmLabel={CONFIRM[pending].label}
          destructive={CONFIRM[pending].destructive}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setPending(null)}
        />
      ) : null}
    </div>
  );
}
