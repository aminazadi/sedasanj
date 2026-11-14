import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "./Widgets";

interface Template {
  event_key: string; title: string; values: string[];
  template_id: number | null; parameters: Record<string, string>; enabled: boolean;
}
interface Delivery {
  id: string; event_key: string; mobile: string; status: string; attempts: number;
  last_error: string | null; created_at: string; sent_at: string | null;
}
interface Row { template_id: string; parameters: string; enabled: boolean }

const STATUS_LABELS: Record<string, string> = {
  pending: "در صف", sent: "ارسال شد", failed: "ناموفق", unknown: "نامشخص (پاسخ دریافت نشد)", skipped: "رد شد (قالب غیرفعال)",
};

function toRow(template: Template): Row {
  return {
    template_id: template.template_id ? String(template.template_id) : "",
    parameters: Object.entries(template.parameters).map(([name, source]) => `${name}=${source}`).join("\n"),
    enabled: template.enabled,
  };
}

function parseParameters(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [name, source] = trimmed.split("=").map((part) => part.trim());
    if (!name || !source) throw new Error(`خط «${trimmed}» را به شکل نام_پارامتر=مقدار بنویسید.`);
    result[name] = source;
  }
  return result;
}

export default function SmsTemplateSettings() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [testMobile, setTestMobile] = useState("");

  async function load() {
    try {
      const [list, log] = await Promise.all([
        request<Template[]>("/v1/admin/sms/templates"),
        request<Delivery[]>("/v1/admin/sms/deliveries?limit=30"),
      ]);
      setTemplates(list); setDeliveries(log);
      setRows(Object.fromEntries(list.map((item) => [item.event_key, toRow(item)])));
    } catch (reason) { setError((reason as Error).message); }
  }
  useEffect(() => { void load(); }, []);

  function patch(key: string, value: Partial<Row>) {
    setRows((current) => ({ ...current, [key]: { ...current[key], ...value } }));
  }

  async function save(key: string) {
    if (busy) return;
    setBusy(key); setError(null); setNotice("");
    try {
      const row = rows[key];
      const saved = await request<Template>(`/v1/admin/sms/templates/${key}`, {
        method: "PUT",
        body: { template_id: row.template_id ? Number(row.template_id) : null, parameters: parseParameters(row.parameters), enabled: row.enabled },
      });
      setTemplates((current) => current?.map((item) => item.event_key === key ? saved : item) ?? current);
      patch(key, toRow(saved)); setNotice("قالب ذخیره شد.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(""); }
  }

  async function test(key: string) {
    if (busy || !testMobile) return;
    setBusy(key); setError(null); setNotice("");
    try {
      await request(`/v1/admin/sms/templates/${key}/test`, { method: "POST", retry: false, body: { mobile: testMobile } });
      setNotice("پیامک آزمایشی با مقدارهای نمونه ارسال شد (یک پیامک هزینه دارد).");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(""); }
  }

  if (!templates) return error ? <ErrorBox message={error}/> : <Loading/>;
  return <section className="card space-y-6" id="settings-panel-sms-templates" role="tabpanel" aria-labelledby="settings-tab-sms-templates">
    <ErrorBox message={error}/>{notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <div className="space-y-2">
      <h2 className="text-lg font-bold">قالب‌های پیامک رویدادها</h2>
      <p className="text-xs leading-6 text-slate-500">
        برای هر رویداد، شناسه قالب خدماتی تأییدشده در SMS.ir را وارد کنید. هر خط پارامتر را به شکل
        <bdi dir="ltr"> نام_پارامتر_در_قالب=مقدار </bdi>
        بنویسید؛ مثلاً <bdi dir="ltr">NAME=ORG</bdi>. کلید API در بخش «تست سریع و پیامک» تنظیم می‌شود. قالب کد تأیید (OTP) هم همان‌جا تنظیم می‌شود؛ کد تأیید عمداً در صف ذخیره نمی‌شود و مستقیم ارسال می‌شود. رویداد بدون قالب فعال ارسال نمی‌شود.
      </p>
      <label className="block max-w-xs"><span className="label">شماره موبایل برای ارسال آزمایشی</span>
        <input className="input" type="tel" dir="ltr" placeholder="09121234567" value={testMobile} onChange={(e) => setTestMobile(fmt.latinDigits(e.target.value))}/>
      </label>
    </div>
    <div className="space-y-4">
      {templates.map((template) => {
        const row = rows[template.event_key];
        if (!row) return null;
        return <div key={template.event_key} className="space-y-3 rounded-2xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold">{template.title}</h3>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={row.enabled} onChange={(e) => patch(template.event_key, { enabled: e.target.checked })}/>فعال</label>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label><span className="label">شناسه قالب</span><input className="input" type="number" min={1} dir="ltr" value={row.template_id} onChange={(e) => patch(template.event_key, { template_id: e.target.value })}/></label>
            <label><span className="label">پارامترها</span><textarea className="input" dir="ltr" rows={Math.max(2, template.values.length)} value={row.parameters} onChange={(e) => patch(template.event_key, { parameters: e.target.value })}/></label>
          </div>
          <p className="text-xs text-slate-500">مقدارهای مجاز: <bdi dir="ltr">{template.values.join("، ")}</bdi></p>
          <div className="flex flex-wrap gap-2">
            <button className="btn" disabled={busy !== ""} onClick={() => void save(template.event_key)}>{busy === template.event_key ? "در حال انجام…" : "ذخیره"}</button>
            <button className="btn-ghost" disabled={busy !== "" || !testMobile || !template.template_id} onClick={() => void test(template.event_key)}>ارسال آزمایشی</button>
          </div>
        </div>;
      })}
    </div>
    <div className="space-y-3 border-t border-slate-200 pt-5">
      <div className="flex items-center justify-between"><h3 className="font-bold">آخرین ارسال‌ها</h3><button className="btn-ghost" onClick={() => void load()}>تازه‌سازی</button></div>
      {deliveries.length === 0 ? <p className="text-sm text-slate-500">هنوز پیامکی ثبت نشده است.</p> :
        <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-right text-slate-500"><th className="p-2">رویداد</th><th className="p-2">گیرنده</th><th className="p-2">وضعیت</th><th className="p-2">تلاش</th><th className="p-2">خطا</th></tr></thead>
          <tbody>{deliveries.map((item) => <tr key={item.id} className="border-t border-slate-100">
            <td className="p-2">{templates.find((entry) => entry.event_key === item.event_key)?.title ?? item.event_key}</td>
            <td className="p-2" dir="ltr">{item.mobile}</td>
            <td className="p-2">{STATUS_LABELS[item.status] ?? item.status}</td>
            <td className="p-2">{item.attempts}</td>
            <td className="p-2 text-xs text-slate-500" dir="ltr">{item.last_error ?? ""}</td>
          </tr>)}</tbody></table></div>}
    </div>
  </section>;
}
