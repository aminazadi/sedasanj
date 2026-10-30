/** Persian text, with the next step, for the billing error codes the API can return. */
export const BILLING_ERRORS = {
  subscription_exists: "اشتراک فعال دارید؛ برای تغییر پلن از بخش «تغییر پلن» در حساب استفاده کنید.",
  change_conflict: "این تغییر الان قابل انجام نیست؛ وضعیت اشتراک را در حساب بررسی کنید.",
  plan_not_sellable: "این پلن برای خرید در دسترس نیست؛ پلن دیگری انتخاب کنید.",
  plan_in_use: "این پلن در حال استفاده است؛ بعد از تغییر مشترکان دوباره تلاش کنید.",
  order_amount_too_large: "مبلغ سفارش از سقف مجاز بیشتر است؛ مقدار را کمتر کنید یا با پشتیبانی تماس بگیرید.",
  conflict_idempotency: "این درخواست قبلاً با اطلاعات دیگری ثبت شده است؛ صفحه را تازه کنید و دوباره تلاش کنید.",
  subscription_inactive: "اشتراک شما فعال نیست؛ از بخش حساب اشتراک را تمدید کنید.",
  insufficient_credit: "اعتبار کافی نیست؛ از بخش حساب اعتبار شارژ کنید.",
  quota_exceeded: "سقف مصرف پلن تمام شده است؛ اعتبار شارژ کنید یا پلن را ارتقا دهید.",
  payment_gateway_unavailable: "درگاه پرداخت پاسخ نمی‌دهد؛ چند دقیقه بعد یا با درگاه دیگری تلاش کنید.",
  payment_method_unavailable: "این روش پرداخت در دسترس نیست؛ روش دیگری انتخاب کنید.",
  not_found: "مورد درخواستی پیدا نشد؛ صفحه را تازه کنید.",
  rate_limited: "تعداد درخواست‌ها زیاد است؛ کمی صبر کنید و دوباره تلاش کنید.",
};

/**
 * The user-facing message for an API error: the mapped Persian text for a known code,
 * the server message when it is already Persian, otherwise the caller's fallback.
 */
export function billingErrorMessage(code, serverMessage, fallback) {
  if (code && BILLING_ERRORS[code]) return BILLING_ERRORS[code];
  if (serverMessage && /[؀-ۿ]/.test(serverMessage)) return serverMessage;
  return fallback;
}
