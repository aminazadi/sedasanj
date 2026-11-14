import { Link } from "react-router-dom";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { fmt } from "../api";
import { MAX_EXTRA_OPERATORS, PLAN_IMAGES, useCheckout } from "../pages/Checkout";
import FormDialog from "./FormDialog";
import PaymentMethodPicker from "./PaymentMethodPicker";

/** Plan choice and payment in the same dialog shell as the other forms. */
export default function CheckoutDialog({ open, initialPlan, onClose }: { open: boolean; initialPlan: string | null; onClose: () => void }) {
  return open ? <CheckoutDialogBody initialPlan={initialPlan} onClose={onClose} /> : null;
}

function CheckoutDialogBody({ initialPlan, onClose }: { initialPlan: string | null; onClose: () => void }) {
  const c = useCheckout(initialPlan);
  const { plan } = c;
  return (
    <FormDialog
      open
      wide
      title="خرید اشتراک"
      description={c.taxPercent ? `قیمت پلن بدون مالیات است و ${fmt.int(c.taxPercent)}٪ مالیات به مبلغ اضافه می‌شود.` : "قیمت نمایش‌داده‌شده شامل مالیات است."}
      submitLabel={plan ? `پرداخت امن · ${fmt.toman(c.lines.total)}` : "پرداخت امن"}
      busy={c.busy}
      submitDisabled={!plan || !c.anyMethod || !c.gateway}
      error={c.error || null}
      onClose={onClose}
      onSubmit={() => void c.submit()}
    >
      {!c.plans ? <p>در حال دریافت اطلاعات پلن…</p> : null}
      {c.plans && !plan ? <p>در حال حاضر هیچ پلنی برای خرید در دسترس نیست؛ با پشتیبانی تماس بگیرید.</p> : null}
      {plan ? (
        <>
          <div className="plan-picker" role="radiogroup" aria-label="انتخاب پلن">
            {c.sellable.map((item) => {
              const selected = item.code === plan.code;
              return (
                <button key={item.code} type="button" role="radio" aria-checked={selected} className={`plan-option${selected ? " is-selected" : ""}`} onClick={() => c.setPicked(item.code)}>
                  {item.featured ? <em className="plan-option__badge">پیشنهادی</em> : null}
                  <span className="plan-option__check" aria-hidden="true">{selected ? "✓" : ""}</span>
                  {PLAN_IMAGES[item.code] ? <img src={PLAN_IMAGES[item.code]} alt="" className="plan-option__image" /> : null}
                  <strong>{item.name}</strong>
                  <b className="plan-option__price">{fmt.toman(item.annual_price_toman ?? 0)}<small> / سال</small></b>
                  <ul className="plan-option__features">
                    <li>{fmt.int(item.base_operators)} اپراتور</li>
                    <li>{fmt.int(item.monthly_included_minutes)} دقیقه در ماه</li>
                    <li>{fmt.int(item.assistant_monthly_messages)} پیام دستیار</li>
                  </ul>
                </button>
              );
            })}
          </div>
          {plan.allows_extra_operators ? (
            <label>
              <span>اپراتور اضافه</span>
              <input type="number" min={0} max={MAX_EXTRA_OPERATORS} inputMode="numeric" value={c.extra}
                onChange={(event) => c.setExtra(Math.max(0, Math.min(MAX_EXTRA_OPERATORS, Number(fmt.latinDigits(event.target.value)) || 0)))} />
            </label>
          ) : null}
          <label><span>نام خریدار</span><input required autoComplete="name" value={c.form.name} onChange={(event) => c.setForm({ ...c.form, name: event.target.value })} /></label>
          <label><span>ایمیل</span><input type="email" dir="ltr" required autoComplete="email" value={c.form.email} onChange={(event) => c.setForm({ ...c.form, email: event.target.value })} /></label>
          <label><span>موبایل</span><input type="tel" dir="ltr" required autoComplete="tel" value={c.form.mobile} onChange={(event) => c.setForm({ ...c.form, mobile: fmt.latinDigits(event.target.value) })} /></label>
          <ToggleSwitch className="terms-check" checked={c.termsAccepted} onChange={c.setTermsAccepted} label="قوانین، حریم خصوصی و سیاست لغو را می‌پذیرم." />
          <p>
            متن کامل: <Link to="/terms" target="_blank">قوانین</Link>، <Link to="/privacy" target="_blank">حریم خصوصی</Link>، <Link to="/cancellation" target="_blank">سیاست لغو</Link>
          </p>
          <PaymentMethodPicker amountToman={c.lines.total} value={c.gateway} onChange={c.setGateway} onAvailability={c.setAnyMethod} />
          <dl className="checkout-lines">
            <div><dt>اشتراک سالانه {plan.name}</dt><dd>{fmt.toman(c.lines.base)}</dd></div>
            {c.extra && plan.allows_extra_operators ? <div><dt>{fmt.int(c.extra)} اپراتور اضافه</dt><dd>{fmt.toman(c.lines.extras)}</dd></div> : null}
            {c.taxPercent ? <div><dt>مالیات ({fmt.int(c.taxPercent)}٪)</dt><dd>{fmt.toman(c.lines.tax)}</dd></div> : null}
            <div className="is-total"><dt>مبلغ نهایی</dt><dd>{fmt.toman(c.lines.total)}</dd></div>
          </dl>
        </>
      ) : null}
    </FormDialog>
  );
}
