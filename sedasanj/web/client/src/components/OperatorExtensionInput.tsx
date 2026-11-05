import { useId } from "react";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { fmt, request } from "../api";
import type { PbxExtension } from "../types";

export default function OperatorExtensionInput({ value, onChange, disabled, invalid = false, errorId }: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  errorId?: string;
}) {
  const id = useId();
  const extensions = useResource<PbxExtension[]>(
    signal => request<PbxExtension[]>("/v1/extensions", { signal }), [],
  );
  const failed = extensions.status === "error";
  return (
    <div>
      <label>
        <span>شماره داخلی</span>
        <input className="input" dir="ltr" inputMode="numeric" list={`${id}-options`}
          value={value} disabled={disabled} aria-invalid={invalid}
          aria-describedby={[`${id}-hint`, errorId].filter(Boolean).join(" ")}
          placeholder="انتخاب داخلی یا ورود مقدار دلخواه"
          onChange={event => onChange(fmt.latinDigits(event.target.value))} />
      </label>
      <datalist id={`${id}-options`}>
        {(extensions.data ?? []).map(extension => (
          <option key={extension.id} value={extension.extension}>
            {[extension.pbx_name, extension.user_name].filter(Boolean).join(" — ") || extension.extension}
          </option>
        ))}
      </datalist>
      <p id={`${id}-hint`} className="text-sm text-slate-500">
        {extensions.loading ? "در حال دریافت داخلی‌ها؛ می‌توانید شمارهٔ دلخواه را وارد کنید."
          : failed ? "دریافت داخلی‌ها ممکن نشد؛ شماره را دستی وارد کنید یا دوباره تلاش کنید."
            : extensions.data?.length ? "از داخلی‌های دریافتی ماژول انتخاب کنید یا شمارهٔ دلخواه بنویسید."
              : "هنوز داخلی‌ای دریافت نشده؛ داخلی‌ها را در ماژول همگام کنید یا شمارهٔ دلخواه بنویسید."}
      </p>
      {failed ? <button type="button" className="btn-ghost" disabled={disabled}
        onClick={() => extensions.reload()}>دریافت دوبارهٔ داخلی‌ها</button> : null}
    </div>
  );
}
