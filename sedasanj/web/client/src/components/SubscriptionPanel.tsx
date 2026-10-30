import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import type { SubscriptionInfo } from "../types";
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
  const status = subscription.grace_ends_at ? "grace" : subscription.status;
  const live = ["active", "trialing", "grace"].includes(status);
  const change = subscription.scheduled_change;

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

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-bold">اشتراک سازمان{subscription.plan_name ? ` · ${subscription.plan_name}` : ""}</h2>
          <p className="section-hint">
            وضعیت: {STATUS_LABELS[status] ?? status} · ظرفیت {fmt.int(subscription.max_operators)} اپراتور ·{" "}
            {fmt.int(subscription.plan_monthly_minutes)} دقیقه رایگان در ماه · پیام دستیار:{" "}
            {fmt.int(subscription.assistant_messages_used)} از {fmt.int(subscription.assistant_monthly_messages)} (باقی‌مانده{" "}
            {fmt.int(subscription.assistant_messages_remaining)})
          </p>
          {subscription.period_end ? <p className="field-hint">سررسید: {fmt.date(subscription.period_end)}</p> : null}
          {subscription.grace_ends_at ? (
            <p className="commerce-error">دوره اشتراک تمام شده است؛ تا {fmt.date(subscription.grace_ends_at)} فرصت دارید تمدید کنید.</p>
          ) : null}
          {subscription.cancel_at_period_end ? (
            <p className="field-hint">لغو شده است و پس از سررسید تمدید نمی‌شود.</p>
          ) : null}
          {change ? (
            <p className="field-hint">
              {change.kind === "downgrade" ? "تنزل" : "ارتقا"} به {change.target_plan_name ?? change.target_plan_code}
              {change.effective_at ? ` از ${fmt.date(change.effective_at)}` : ""} برنامه‌ریزی شده است.
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {live && subscription.status === "active" ? <Link className="btn" to="/billing/change-plan">تغییر پلن</Link> : null}
          {subscription.status === "trialing" ? <Link className="btn" to="/#pricing">خرید پلن</Link> : null}
          {change ? <button className="btn-ghost" onClick={() => setPending("cancel_change")}>لغو تغییر پلن</button> : null}
          {live && !subscription.cancel_at_period_end && subscription.status === "active" ? (
            <button className="btn-ghost" onClick={() => setPending("cancel")}>لغو در پایان دوره</button>
          ) : null}
          {subscription.cancel_at_period_end && live ? <button className="btn-ghost" onClick={() => setPending("resume")}>ازسرگیری</button> : null}
        </div>
      </div>
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
