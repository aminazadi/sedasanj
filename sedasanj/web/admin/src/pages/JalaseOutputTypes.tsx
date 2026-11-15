import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, request, uploadWithProgress } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";

const BASE = "/v1/admin/jalase/output-types";
const MEDIA = "/v1/admin/help/media";

type Field = { key: string; label_fa: string; type: "text" | "select" | "number"; required: boolean; max_len: number; options?: string[] };
type Version = {
  id: string; version: number; state: "draft" | "published" | "superseded"; mode: "summarize" | "transform";
  map_instruction: string; system_prompt: string; input_fields: Field[];
  llm_provider: string | null; llm_model: string | null;
};
type OutputType = {
  id: string; code: string; title_fa: string; description_fa: string; menu_label_fa: string;
  thumbnail_url: string | null; thumbnail_media_id: string | null; sort_order: number;
  status: "draft" | "published" | "archived"; builtin: boolean; versions: Version[];
};
type Media = { id: string; kind: "image" | "video"; filename: string; url: string };

const STATUS = { draft: "پیش‌نویس", published: "منتشرشده", archived: "بایگانی" } as const;
const STATE = { draft: "پیش‌نویس", published: "منتشرشده", superseded: "جایگزین‌شده" } as const;
const FIELD_TYPES = { text: "متن", select: "انتخابی", number: "عدد" } as const;

const message = (reason: unknown) =>
  reason instanceof ApiError
    ? reason.message
    : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";

export default function JalaseOutputTypes() {
  const [items, setItems] = useState<OutputType[] | null>(null);
  const [media, setMedia] = useState<Media[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState({ code: "", title_fa: "", menu_label_fa: "" });

  const reload = useCallback(async () => {
    try {
      const [types, library] = await Promise.all([request<OutputType[]>(BASE), request<Media[]>(MEDIA)]);
      setItems(types);
      setMedia(library.filter((m) => m.kind === "image"));
    } catch (reason) {
      setError(message(reason));
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  async function run(action: () => Promise<unknown>, done: string) {
    if (busy) return;
    setBusy(true); setError(null); setNotice("");
    try {
      await action();
      setNotice(done);
      await reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const made = await request<OutputType>(BASE, { method: "POST", body: creating });
      setCreating({ code: "", title_fa: "", menu_label_fa: "" });
      setSelected(made.id);
    }, "دسته ساخته شد؛ پرامپت آن را بنویسید و منتشر کنید.");
  }

  if (!items) return error ? <ErrorBox message={error} /> : <Loading />;
  const current = items.find((item) => item.id === selected) ?? null;

  return <div className="space-y-5">
    <ErrorBox message={error} />
    {notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <div className="card space-y-2">
      <h1 className="text-lg font-bold">دسته‌های تبدیل جلسه‌نگار</h1>
      <p className="text-sm text-slate-500">فقط ادمین دسته می‌سازد. کاربر در هر ارسال یک یا چند دسته‌ی منتشرشده را انتخاب می‌کند. نسخهٔ منتشرشده ویرایش نمی‌شود؛ هر تغییر یک پیش‌نویس جدید است که پس از انتشار جای نسخهٔ قبلی را می‌گیرد.</p>
      <form className="grid gap-2 md:grid-cols-4" onSubmit={(e) => void create(e)}>
        <input className="input" dir="ltr" placeholder="کد انگلیسی (مثلاً counseling)" pattern="[a-z][a-z0-9_]{1,39}" required value={creating.code} onChange={(e) => setCreating({ ...creating, code: e.target.value })}/>
        <input className="input" placeholder="عنوان فارسی" minLength={2} maxLength={120} required value={creating.title_fa} onChange={(e) => setCreating({ ...creating, title_fa: e.target.value })}/>
        <input className="input" placeholder="برچسب منو" minLength={2} maxLength={60} required value={creating.menu_label_fa} onChange={(e) => setCreating({ ...creating, menu_label_fa: e.target.value })}/>
        <button className="btn" disabled={busy}>دستهٔ جدید</button>
      </form>
    </div>

    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => <button type="button" key={item.id} onClick={() => setSelected(item.id)}
        className={`card flex items-center gap-3 text-start ${item.id === selected ? "ring-2 ring-sky-500" : ""}`}>
        {item.thumbnail_url
          ? <img src={item.thumbnail_url} alt="" className="h-14 w-14 rounded object-cover"/>
          : <span className="flex h-14 w-14 items-center justify-center rounded bg-slate-100 text-xs text-slate-400">بدون تصویر</span>}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{item.title_fa}</span>
          <span className="block text-xs text-slate-500" dir="ltr">{item.code}</span>
          <span className={`badge mt-1 ${item.status === "published" ? "bg-emerald-50 text-emerald-700" : item.status === "draft" ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
            {STATUS[item.status]}{item.builtin ? " · داخلی" : ""}
          </span>
        </span>
      </button>)}
    </div>

    {current && <Editor key={current.id + current.versions.map((v) => v.id + v.state).join()} item={current} media={media} busy={busy} run={run} onMediaChange={reload} setError={setError}/>}
  </div>;
}

function Editor({ item, media, busy, run, onMediaChange, setError }: {
  item: OutputType; media: Media[]; busy: boolean;
  run: (action: () => Promise<unknown>, done: string) => Promise<void>;
  onMediaChange: () => Promise<void>; setError: (message: string | null) => void;
}) {
  const draft = item.versions.find((v) => v.state === "draft");
  const base = draft ?? item.versions[0];
  const [meta, setMeta] = useState({ title_fa: item.title_fa, description_fa: item.description_fa, menu_label_fa: item.menu_label_fa, sort_order: item.sort_order });
  const [mode, setMode] = useState<Version["mode"]>(base?.mode ?? "summarize");
  const [mapInstruction, setMapInstruction] = useState(base?.map_instruction ?? "");
  const [systemPrompt, setSystemPrompt] = useState(base?.system_prompt ?? "");
  const [fields, setFields] = useState<Field[]>(base?.input_fields ?? []);
  const [provider, setProvider] = useState(base?.llm_provider ?? "");
  const [model, setModel] = useState(base?.llm_model ?? "");
  const [progress, setProgress] = useState<number | null>(null);
  const url = `${BASE}/${item.id}`;

  const updateField = (index: number, patch: Partial<Field>) =>
    setFields(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));

  async function uploadThumbnail(file: File) {
    const form = new FormData();
    form.append("file", file);
    form.append("alt", item.title_fa);
    setProgress(0);
    try {
      const uploaded = await uploadWithProgress<Media>(MEDIA, form, setProgress);
      await request(url, { method: "PATCH", body: { thumbnail_media_id: uploaded.id } });
      await onMediaChange();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setProgress(null);
    }
  }

  const draftBody = { mode, map_instruction: mapInstruction, system_prompt: systemPrompt, input_fields: fields, llm_provider: provider, llm_model: model };

  return <div className="card space-y-5">
    <h2 className="text-lg font-bold">{item.title_fa} <span className="text-sm font-normal text-slate-500" dir="ltr">({item.code})</span></h2>

    <section className="space-y-3">
      <h3 className="font-medium">مشخصات و تصویر</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block text-sm"><span className="mb-1 block">عنوان</span><input className="input" maxLength={120} value={meta.title_fa} onChange={(e) => setMeta({ ...meta, title_fa: e.target.value })}/></label>
        <label className="block text-sm"><span className="mb-1 block">برچسب منو (در پنل سازمان)</span><input className="input" maxLength={60} value={meta.menu_label_fa} onChange={(e) => setMeta({ ...meta, menu_label_fa: e.target.value })}/></label>
        <label className="block text-sm md:col-span-2"><span className="mb-1 block">توضیح کوتاه برای کاربر</span><input className="input" maxLength={500} value={meta.description_fa} onChange={(e) => setMeta({ ...meta, description_fa: e.target.value })}/></label>
        <label className="block text-sm"><span className="mb-1 block">ترتیب نمایش (عدد کمتر، بالاتر)</span><input className="input" type="number" min={0} max={100000} value={meta.sort_order} onChange={(e) => setMeta({ ...meta, sort_order: Number(e.target.value) })}/></label>
        <label className="block text-sm"><span className="mb-1 block">بارگذاری تصویر تازه (png، jpg یا webp)</span>
          <input className="input" type="file" accept="image/png,image/jpeg,image/webp" disabled={progress !== null} onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadThumbnail(f); }}/></label>
      </div>
      {progress !== null && <progress className="w-full" value={progress} max={1} aria-label="پیشرفت بارگذاری"/>}
      {media.length > 0 && <div>
        <p className="mb-1 text-sm">یا از کتابخانه انتخاب کنید:</p>
        <div className="flex flex-wrap gap-2">
          {media.map((m) => <button type="button" key={m.id} title={m.filename}
            onClick={() => void run(() => request(url, { method: "PATCH", body: { thumbnail_media_id: m.id } }), "تصویر دسته تغییر کرد.")}
            className={`rounded border p-0.5 ${m.id === item.thumbnail_media_id ? "ring-2 ring-sky-500" : ""}`}>
            <img src={m.url} alt={m.filename} className="h-12 w-12 rounded object-cover"/></button>)}
        </div>
      </div>}
      <div className="flex gap-2">
        <button className="btn" disabled={busy} onClick={() => void run(() => request(url, { method: "PATCH", body: meta }), "مشخصات ذخیره شد.")}>ذخیرهٔ مشخصات</button>
        {item.thumbnail_media_id && <button className="btn-ghost" disabled={busy} onClick={() => void run(() => request(url, { method: "PATCH", body: { clear_thumbnail: true } }), "تصویر برداشته شد.")}>برداشتن تصویر</button>}
      </div>
    </section>

    {item.builtin
      ? <p className="rounded bg-slate-50 p-3 text-sm text-slate-600">پرامپت این دستهٔ داخلی از «پرامپت صورت‌جلسه» در تنظیمات مدل‌ها خوانده می‌شود و اینجا تغییر نمی‌کند.</p>
      : <section className="space-y-3">
        <h3 className="font-medium">پرامپت {draft ? `(پیش‌نویس نسخهٔ ${draft.version})` : "(با ذخیره، پیش‌نویس جدید ساخته می‌شود)"}</h3>
        <label className="block text-sm"><span className="mb-1 block">حالت</span>
          <select className="input" value={mode} onChange={(e) => setMode(e.target.value as Version["mode"])}>
            <option value="summarize">خلاصه‌سازی (خلاصهٔ هر بخش، سپس سند ساختاریافته)</option>
            <option value="transform">بازنویسی (هر بخش بازنویسی و به هم چسبانده می‌شود، بدون خلاصه)</option>
          </select></label>
        {mode === "summarize" && <label className="block text-sm"><span className="mb-1 block">دستور خلاصهٔ هر بخش (برای متن‌های بلند)</span>
          <textarea className="input min-h-24" maxLength={4000} value={mapInstruction} onChange={(e) => setMapInstruction(e.target.value)}/></label>}
        <label className="block text-sm"><span className="mb-1 block">پرامپت اصلی (نقش و بخش‌های سند؛ قالب JSON را سیستم ثابت اضافه می‌کند)</span>
          <textarea className="input min-h-40" maxLength={8000} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)}/></label>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="block text-sm"><span className="mb-1 block">ارائه‌دهندهٔ مدل این دسته (خالی = پیش‌فرض جلسات)</span>
            <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="">پیش‌فرض</option><option value="aiservice">aiservice</option><option value="ninerouter_direct">ninerouter_direct</option>
            </select></label>
          <label className="block text-sm"><span className="mb-1 block">نام مدل این دسته (خالی = پیش‌فرض)</span>
            <input className="input" dir="ltr" maxLength={120} value={model} onChange={(e) => setModel(e.target.value)}/></label>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between"><h4 className="text-sm font-medium">فیلدهای ورودی (اختیاری، حداکثر ۸)</h4>
            <button type="button" className="btn-ghost" disabled={fields.length >= 8} onClick={() => setFields([...fields, { key: "", label_fa: "", type: "text", required: false, max_len: 200 }])}>افزودن فیلد</button></div>
          {fields.map((f, i) => <div key={i} className="grid gap-2 rounded border p-2 md:grid-cols-6">
            <input className="input" dir="ltr" placeholder="key" pattern="[a-z][a-z0-9_]{0,29}" value={f.key} onChange={(e) => updateField(i, { key: e.target.value })}/>
            <input className="input md:col-span-2" placeholder="عنوان فارسی" value={f.label_fa} onChange={(e) => updateField(i, { label_fa: e.target.value })}/>
            <select className="input" value={f.type} onChange={(e) => updateField(i, { type: e.target.value as Field["type"] })}>
              {Object.entries(FIELD_TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.required} onChange={(e) => updateField(i, { required: e.target.checked })}/>اجباری</label>
            <button type="button" className="text-rose-700" onClick={() => setFields(fields.filter((_, j) => j !== i))}>حذف</button>
            {f.type === "select" && <input className="input md:col-span-6" placeholder="گزینه‌ها، با ویرگول جدا شوند" value={(f.options ?? []).join("، ")} onChange={(e) => updateField(i, { options: e.target.value.split(/[،,]/).map((o) => o.trim()).filter(Boolean) })}/>}
          </div>)}
        </div>

        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={busy} onClick={() => void run(() => request(`${url}/draft`, { method: "PUT", body: draftBody }), "پیش‌نویس ذخیره شد.")}>ذخیرهٔ پیش‌نویس</button>
          <button className="btn" disabled={busy || !draft} onClick={() => { if (window.confirm("نسخهٔ منتشرشدهٔ فعلی جایگزین می‌شود و کاربران فوراً نسخهٔ جدید را می‌گیرند. ادامه می‌دهید؟")) void run(() => request(`${url}/publish`, { method: "POST" }), "منتشر شد."); }}>انتشار پیش‌نویس</button>
          {item.status !== "archived" && <button className="btn-ghost" disabled={busy} onClick={() => { if (window.confirm("دسته از اپ برداشته می‌شود؛ اسناد ساخته‌شده می‌مانند. ادامه می‌دهید؟")) void run(() => request(`${url}/archive`, { method: "POST" }), "دسته بایگانی شد."); }}>بایگانی</button>}
        </div>
        <p className="text-xs text-slate-500">برای انتشار، پیش‌نویس باید ذخیره شده باشد. دکمهٔ «ذخیرهٔ پیش‌نویس» را بزنید و سپس منتشر کنید.</p>
      </section>}

    <section>
      <h3 className="mb-1 font-medium">تاریخچهٔ نسخه‌ها</h3>
      <ul className="text-sm text-slate-600">{item.versions.map((v) => <li key={v.id}>نسخهٔ {v.version}: {STATE[v.state]} — {v.mode === "summarize" ? "خلاصه‌سازی" : "بازنویسی"}</li>)}</ul>
    </section>
  </div>;
}
