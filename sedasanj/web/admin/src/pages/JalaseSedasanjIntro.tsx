import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";

const path = "/v1/admin/jalase-negar/sedasanj-intro";

type Intro = {
  enabled: boolean;
  delay_days: number;
  title: string;
  body: string;
  video_url: string;
  button_label: string;
  button_url: string;
};

const message = (reason: unknown) =>
  reason instanceof ApiError && reason.code === "invalid_request"
    ? "مقادیر واردشده معتبر نیست. نشانی ویدئو و دکمه باید با https شروع شود و طول متن‌ها از حد مجاز بیشتر نباشد؛ اصلاح و دوباره ذخیره کنید."
    : reason instanceof ApiError
      ? reason.message
      : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";

export default function JalaseSedasanjIntro() {
  const [value, setValue] = useState<Intro | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<Intro>(path).then(setValue, (reason) => setError(message(reason)));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      setValue(await request<Intro>(path, { method: "PUT", body: value }));
      setNotice("تنظیمات ذخیره شد.");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!value) return error ? <ErrorBox message={error} /> : <Loading />;
  const set = (patch: Partial<Intro>) => setValue({ ...value, ...patch });

  return <section className="card space-y-5">
    <div>
      <h1 className="text-lg font-bold">معرفی صداسنج در جلسه‌نگار</h1>
      <p className="mt-1 text-sm text-slate-500">اگر کاربر پس از مدتی استفاده هنوز به صداسنج وصل نشده باشد، این معرفی در یک دراور به او نشان داده می‌شود.</p>
    </div>
    <ErrorBox message={error} />
    {notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <form className="space-y-5" onSubmit={save}>
      <fieldset disabled={busy} className="space-y-5">
        <label className="flex items-center gap-2"><input type="checkbox" checked={value.enabled} onChange={(e) => set({ enabled: e.target.checked })} /><span>نمایش معرفی در جلسه‌نگار فعال باشد</span></label>
        <label className="block"><span className="label">تعداد روز استفاده تا نمایش اول (صفر: همان ابتدا)</span><input className="input" type="number" min={0} max={365} dir="ltr" required value={value.delay_days} onChange={(e) => set({ delay_days: Number(e.target.value) })} /></label>
        <label className="block"><span className="label">عنوان</span><input className="input" required maxLength={120} value={value.title} onChange={(e) => set({ title: e.target.value })} /></label>
        <label className="block"><span className="label">توضیحات صداسنج و فواید اتصال</span><textarea className="input min-h-40" required maxLength={2000} value={value.body} onChange={(e) => set({ body: e.target.value })} /></label>
        <label className="block"><span className="label">نشانی ویدئو (اختیاری، MP4 با https)</span><input className="input text-left" dir="ltr" type="url" maxLength={2048} placeholder="https://" value={value.video_url} onChange={(e) => set({ video_url: e.target.value })} /></label>
        <p className="text-xs leading-6 text-slate-500">ویدئو را می‌توانید از «مرکز راهنما ← تصویر و ویدئو» بارگذاری و نشانی آن را اینجا وارد کنید. خالی بودن یعنی بدون ویدئو.</p>
        <label className="block"><span className="label">متن دکمه</span><input className="input" required maxLength={40} value={value.button_label} onChange={(e) => set({ button_label: e.target.value })} /></label>
        <label className="block"><span className="label">لینک دکمه</span><input className="input text-left" dir="ltr" type="url" required maxLength={2048} value={value.button_url} onChange={(e) => set({ button_url: e.target.value })} /></label>
        <p className="text-xs leading-6 text-slate-500">پیش‌فرض: https://sedasanj.ir . کاربر می‌تواند با گزینهٔ «با صداسنج آشنا هستم و دیگر نمایش نده» نمایش را برای خودش متوقف کند.</p>
        <button className="btn" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره"}</button>
      </fieldset>
    </form>
  </section>;
}
