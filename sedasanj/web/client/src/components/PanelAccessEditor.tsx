import { useResource } from "@cbi/web-shared/lib/useResource";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { request } from "../api";
import type { PanelAccessOption } from "../lib/panelAccess";

export default function PanelAccessEditor({ role, value, onChange, disabled }: {
  role: string;
  value: string[] | null;
  onChange: (value: string[] | null) => void;
  disabled?: boolean;
}) {
  const options = useResource<PanelAccessOption[]>(signal => request("/v1/auth/panel-access-options", { signal }), []);
  const available = (options.data ?? []).filter(option => option.roles.includes(role));
  const selected = value ?? available.map(option => option.key);
  const all = available.filter(option => option.assignable).map(option => option.key);
  return <fieldset className="min-w-0 border border-[color:var(--line)] p-3" disabled={disabled}>
    <legend className="px-1 font-bold">دسترسی به بخش‌های پنل</legend>
    <p className="text-sm">بخش‌های مجاز را انتخاب کنید. پروفایل و راهنما همیشه در دسترس‌اند؛ محدودیت اطلاعات و عملیات هر نقش حفظ می‌شود.</p>
    {options.loading ? <p role="status">در حال دریافت بخش‌ها…</p> : null}
    {options.status === "error" ? <p role="alert">دریافت بخش‌ها ممکن نشد؛ دسترسی ذخیره‌شده حفظ می‌شود. <button type="button" className="btn-ghost" onClick={() => options.reload()}>تلاش دوباره</button></p> : null}
    {options.data ? <>
      <div className="my-3 flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={() => onChange(all)}>انتخاب همه</button>
        <button type="button" className="btn-ghost" onClick={() => onChange([])}>لغو انتخاب‌ها</button>
        <button type="button" className="btn-ghost" disabled={available.some(option => !option.assignable)} onClick={() => onChange(null)}>پیش‌فرض نقش</button>
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        {options.data.map(option => {
          const allowed = option.roles.includes(role);
          const checked = allowed && selected.includes(option.key);
          return <ToggleSwitch key={option.key} checked={checked}
            label={`${option.label}${!allowed ? " (نیازمند نقش بالاتر)" : ""}`}
            className="min-w-0 items-start" labelClassName={`min-w-0 whitespace-normal break-words text-sm ${!allowed ? "text-slate-400" : ""}`}
            disabled={disabled || !allowed || (!option.assignable && !checked)}
            onChange={next => onChange(next ? [...selected, option.key] : selected.filter(key => key !== option.key))} />;
        })}
      </div>
      <p className="mt-3 text-sm">{value === null ? "دسترسی‌های پیش‌فرض نقش اعمال می‌شود." : `دسترسی سفارشی: ${available.filter(option => selected.includes(option.key)).length} بخش انتخاب شده است.`}</p>
    </> : null}
  </fieldset>;
}
