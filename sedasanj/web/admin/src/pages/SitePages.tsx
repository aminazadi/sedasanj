import { useCallback, useEffect, useMemo, useState } from "react";
import { request, uploadWithProgress } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";

type Content = Record<string, unknown>;
type Leaf = { key: string; label: string; hint?: string; kind: "text" | "area" | "link" | "select" | "checkbox" | "image" | "video" | "number"; rows?: number; min?: number; max?: number; options?: Array<[string, string]> };
type Field =
  | Leaf
  | { key: string; label: string; hint?: string; kind: "list"; itemLabel: string; max: number; area?: boolean }
  | { key: string; label: string; hint?: string; kind: "objects"; itemLabel: string; max: number; fields: Leaf[] };

interface PageView { slug: string; content: Content; is_default: boolean; updated_at: string | null }

const TITLE_HINT = "برای رفتن به خط بعد، Enter بزنید. متن بین دو ** (مثل **این**) رنگی نمایش داده می‌شود.";
const LINK_HINT = "مسیر داخلی (/contact)، https://، tel: یا mailto: — خالی یعنی بدون پیوند.";

const ICON_OPTIONS: Array<[string, string]> = [["", "بدون آیکن"], ["target", "هدف"], ["users", "افراد"], ["shield", "سپر امنیت"], ["lock", "قفل"], ["chart", "نمودار"], ["trend", "روند رو به رشد"], ["pulse", "ضربان"], ["message", "پیام"], ["headset", "هدست"], ["tasks", "فهرست کارها"], ["brain", "هوش"], ["layers", "لایه‌ها"], ["spark", "جرقه"], ["clock", "ساعت"], ["phone", "تلفن"]];

const LEGAL: Field[] = [
  { key: "title", label: "عنوان صفحه", kind: "text" },
  { key: "intro", label: "مقدمه", kind: "area", rows: 3 },
  { key: "updated_label", label: "تاریخ آخرین بروزرسانی", kind: "text", hint: "مثلاً «آخرین بروزرسانی: ۱۴۰۵/۰۷/۱۰». خالی یعنی نمایش داده نشود." },
  { key: "sections", label: "بخش‌های متن", kind: "objects", itemLabel: "بخش", max: 40, hint: "هر بخش یک عنوان و متن دارد؛ برای پاراگراف جدید یک خط خالی بگذارید.", fields: [
    { key: "title", label: "عنوان بخش", kind: "text" },
    { key: "body", label: "متن بخش", kind: "area", rows: 8 },
  ] },
];

const SCHEMAS: Record<string, { label: string; path: string; fields: Field[] }> = {
  about: { label: "درباره ما", path: "/about", fields: [
    { key: "hero_title", label: "عنوان اصلی", kind: "area", rows: 3, hint: TITLE_HINT },
    { key: "hero_text", label: "توضیح زیر عنوان", kind: "area", rows: 4 },
    { key: "story_title", label: "عنوان بخش مسئله", kind: "area", rows: 2, hint: TITLE_HINT },
    { key: "story_paragraphs", label: "پاراگراف‌های بخش مسئله", kind: "list", itemLabel: "پاراگراف", max: 6, area: true },
    { key: "values_title", label: "عنوان بخش اصول", kind: "text" },
    { key: "values", label: "اصول", kind: "objects", itemLabel: "اصل", max: 6, fields: [
      { key: "icon", label: "آیکن", kind: "select", options: ICON_OPTIONS },
      { key: "title", label: "عنوان", kind: "text" },
      { key: "text", label: "توضیح", kind: "area", rows: 3 },
    ] },
    { key: "outcome_title", label: "عنوان بخش پایانی", kind: "area", rows: 2, hint: TITLE_HINT },
    { key: "outcome_text", label: "متن بخش پایانی", kind: "area", rows: 3 },
    { key: "outcome_button", label: "متن دکمه", kind: "text" },
    { key: "outcome_link", label: "پیوند دکمه", kind: "link", hint: LINK_HINT },
  ] },
  contact: { label: "تماس با ما", path: "/contact", fields: [
    { key: "hero_title", label: "عنوان اصلی", kind: "area", rows: 3, hint: TITLE_HINT },
    { key: "hero_text", label: "توضیح زیر عنوان", kind: "area", rows: 3 },
    { key: "aside_title", label: "عنوان کارت ارتباط", kind: "text" },
    { key: "methods", label: "راه‌های ارتباطی", kind: "objects", itemLabel: "راه ارتباطی", max: 6, hint: "شماره تلفن، ایمیل، نشانی یا ساعت کاری را اینجا اضافه کنید.", fields: [
      { key: "icon", label: "آیکن", kind: "select", options: [["phone", "تلفن"], ["mail", "ایمیل"], ["sales", "فروش"], ["clock", "ساعت کاری"], ["location", "نشانی"], ["chat", "پیام"]] },
      { key: "label", label: "عنوان کوچک", kind: "text" },
      { key: "value", label: "مقدار نمایشی", kind: "text" },
      { key: "href", label: "پیوند (اختیاری)", kind: "link", hint: LINK_HINT },
    ] },
    { key: "form_title", label: "عنوان فرم", kind: "text" },
    { key: "form_message_placeholder", label: "راهنمای کادر پیام", kind: "text" },
    { key: "form_submit", label: "متن دکمه ارسال", kind: "text" },
    { key: "form_success", label: "پیام موفقیت", kind: "area", rows: 2 },
  ] },
  terms: { label: "قوانین استفاده", path: "/terms", fields: LEGAL },
  privacy: { label: "حریم خصوصی", path: "/privacy", fields: LEGAL },
  cancellation: { label: "لغو اشتراک", path: "/cancellation", fields: LEGAL },
  auth_aside: { label: "پنل صفحه ورود و ثبت‌نام", path: "/login", fields: [
    { key: "messages", label: "پیام‌ها", kind: "objects", itemLabel: "پیام", max: 8, hint: "پیام‌ها یکی‌یکی تایپ می‌شوند و بعد از مکث، پیام بعدی جایگزین می‌شود. دکمه اختیاری است؛ متن و پیوند آن باید با هم پر شوند.", fields: [
      { key: "text", label: "متن پیام", kind: "text" },
      { key: "cta_text", label: "متن دکمه (اختیاری)", kind: "text" },
      { key: "cta_link", label: "پیوند دکمه", kind: "link", hint: LINK_HINT },
    ] },
    { key: "type_speed_ms", label: "سرعت تایپ (میلی‌ثانیه برای هر حرف)", kind: "number", min: 20, max: 200, hint: "عدد کمتر یعنی تایپ سریع‌تر. پیش‌فرض ۵۵." },
    { key: "hold_seconds", label: "مکث بعد از تایپ (ثانیه)", kind: "number", min: 1, max: 30, hint: "مدت نمایش هر پیام قبل از جایگزین‌شدن. پیش‌فرض ۴." },
  ] },
  landing_video: { label: "ویدئوی صفحه اصلی", path: "/", fields: [
    { key: "title", label: "متن دکمه شناور", kind: "text", hint: "پیش‌فرض: «چرا صداسنج؟». خالی بگذارید تا همین متن نمایش داده شود." },
    { key: "avatar_media_id", label: "آواتار (GIF یا تصویر)", kind: "image", hint: "تصویر کنار متن دکمه شناور و پشت دکمه پخش در بالای صفحه. اگر خالی باشد بدون آواتار نمایش داده می‌شود." },
    { key: "video_media_id", label: "ویدئوی اصلی", kind: "video", hint: "با کلیک روی دکمه، در پنل ویدئو پخش می‌شود. تا زمانی که بارگذاری نشود، دکمه و پنل نمایش داده نمی‌شوند. فرمت MP4 یا WebM، حداکثر ۱۲۰ مگابایت." },
    { key: "play_caption", label: "متن زیر دکمه پخش صفحه اصلی", kind: "text", hint: "زیر آیکن پخش در بالای صفحه اصلی نمایش داده می‌شود. خالی یعنی متنی نمایش داده نشود." },
    { key: "autoplay", label: "پخش خودکار ویدئوی اصلی با باز شدن پنل", kind: "checkbox" },
    { key: "panel_position", label: "جای پنل روی صفحه", kind: "select", options: [["start", "گوشه پایین، سمت راست صفحه"], ["end", "گوشه پایین، سمت چپ صفحه"]] },
    { key: "questions", label: "سؤال‌های روی ویدئو", kind: "objects", itemLabel: "سؤال", max: 8, hint: "هر سؤال با ویدئوی پاسخ خودش روی پنل نمایش داده می‌شود؛ پس از دیدن پاسخ، سؤال از فهرست کنار می‌رود. هر سؤال هم متن و هم ویدئو لازم دارد.", fields: [
      { key: "question", label: "متن سؤال", kind: "text" },
      { key: "video_media_id", label: "ویدئوی پاسخ", kind: "video", hint: "فرمت MP4 یا WebM." },
    ] },
    { key: "cta_button_text", label: "متن دکمه پایانی", kind: "text", hint: "بعد از پایان آخرین پاسخ نمایش داده می‌شود. خالی یعنی دکمه نمایش داده نشود." },
    { key: "cta_button_link", label: "پیوند دکمه پایانی", kind: "link", hint: LINK_HINT },
    { key: "cta_phone_label", label: "متن کنار شماره تلفن", kind: "text", hint: "مثلاً «راهنمایی نیاز دارید؟»" },
    { key: "cta_phone", label: "شماره تلفن", kind: "text", hint: "فقط رقم، + و فاصله. خالی یعنی نمایش داده نشود." },
  ] },
};
const ORDER = ["about", "contact", "terms", "privacy", "cancellation", "auth_aside", "landing_video"];

/** Picks a file, uploads it to the media library and hands back the new media id. */
const MEDIA_ACCEPT = { image: "image/gif,image/png,image/jpeg,image/webp", video: "video/mp4,video/webm" } as const;

function MediaField({ label, hint, kind, value, onChange }: { label: string; hint?: string; kind: "image" | "video"; value: string; onChange: (id: string) => void }) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function upload(file: File) {
    setError(null);
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    try {
      const media = await uploadWithProgress<{ id: string; kind: string }>("/v1/admin/help/media", form, setProgress);
      if (media.kind !== kind) throw new Error(kind === "image" ? "فقط فایل تصویر یا GIF مجاز است." : "فقط فایل ویدئو (MP4 یا WebM) مجاز است.");
      onChange(media.id);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setProgress(null);
    }
  }
  const url = value ? `/v1/help/media/${value}` : "";
  return <fieldset className="space-y-3 rounded-lg border border-slate-200 p-4">
    <legend className="label px-2">{label}</legend>
    {hint && <p className="text-xs text-slate-500">{hint}</p>}
    {url && (kind === "image" ? <img src={url} alt="" className="h-20 w-20 rounded-full border object-cover" /> : <video src={url} controls preload="metadata" className="max-h-56 rounded" />)}
    <div className="flex flex-wrap items-center gap-3">
      <input type="file" accept={MEDIA_ACCEPT[kind]} disabled={progress !== null} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(file); }} />
      {progress !== null && <span className="text-xs text-slate-500" role="status">در حال بارگذاری… {Math.round(progress * 100)}٪</span>}
      {value && progress === null && <button type="button" className="btn-ghost text-red-700" onClick={() => onChange("")}>حذف</button>}
    </div>
    {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
  </fieldset>;
}

function LeafInput({ field, value, onChange }: { field: Leaf; value: string; onChange: (value: string) => void }) {
  if (field.kind === "select") {
    return <select className="input" value={value} onChange={(event) => onChange(event.target.value)}>{field.options?.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>;
  }
  if (field.kind === "area") {
    return <textarea className="input leading-7" rows={field.rows ?? 4} value={value} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.kind === "number") {
    return <input className="input" type="number" dir="ltr" min={field.min} max={field.max} value={value} onChange={(event) => onChange(event.target.value)} />;
  }
  return <input className="input" dir={field.kind === "link" ? "ltr" : undefined} value={value} onChange={(event) => onChange(event.target.value)} />;
}

function Labeled({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="block"><span className="label">{label}</span>{children}{hint && <span className="mt-1 block text-xs leading-6 text-slate-500">{hint}</span>}</label>;
}

function move<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function RowTools({ index, count, onMove, onRemove }: { index: number; count: number; onMove: (to: number) => void; onRemove: () => void }) {
  return <div className="flex gap-1 text-xs">
    <button type="button" className="btn-ghost" disabled={index === 0} onClick={() => onMove(index - 1)} aria-label="انتقال به بالا">▲</button>
    <button type="button" className="btn-ghost" disabled={index === count - 1} onClick={() => onMove(index + 1)} aria-label="انتقال به پایین">▼</button>
    <button type="button" className="btn-ghost text-red-700" onClick={onRemove}>حذف</button>
  </div>;
}

function FieldEditor({ field, value, onChange }: { field: Field; value: unknown; onChange: (value: unknown) => void }) {
  if (field.kind === "list") {
    const items = (Array.isArray(value) ? value : []) as string[];
    return <fieldset className="space-y-3 rounded-lg border border-slate-200 p-4">
      <legend className="label px-2">{field.label}</legend>
      {field.hint && <p className="text-xs text-slate-500">{field.hint}</p>}
      {items.map((item, index) => <div key={index} className="space-y-2">
        <div className="flex items-center justify-between"><span className="text-xs text-slate-500">{field.itemLabel} {index + 1}</span><RowTools index={index} count={items.length} onMove={(to) => onChange(move(items, index, to))} onRemove={() => onChange(items.filter((_, at) => at !== index))} /></div>
        {field.area ? <textarea className="input leading-7" rows={4} value={item} onChange={(event) => onChange(items.map((old, at) => at === index ? event.target.value : old))} /> : <input className="input" value={item} onChange={(event) => onChange(items.map((old, at) => at === index ? event.target.value : old))} />}
      </div>)}
      <button type="button" className="btn-ghost" disabled={items.length >= field.max} onClick={() => onChange([...items, ""])}>افزودن {field.itemLabel}</button>
    </fieldset>;
  }
  if (field.kind === "objects") {
    const items = (Array.isArray(value) ? value : []) as Array<Record<string, string>>;
    return <fieldset className="space-y-3 rounded-lg border border-slate-200 p-4">
      <legend className="label px-2">{field.label}</legend>
      {field.hint && <p className="text-xs text-slate-500">{field.hint}</p>}
      {items.map((item, index) => <div key={index} className="space-y-3 rounded-lg bg-slate-50 p-3">
        <div className="flex items-center justify-between"><strong className="text-sm">{field.itemLabel} {index + 1}</strong><RowTools index={index} count={items.length} onMove={(to) => onChange(move(items, index, to))} onRemove={() => onChange(items.filter((_, at) => at !== index))} /></div>
        {field.fields.map((sub) => {
          const set = (next: string) => onChange(items.map((old, at) => at === index ? { ...old, [sub.key]: next } : old));
          if (sub.kind === "image" || sub.kind === "video") return <MediaField key={sub.key} label={sub.label} hint={sub.hint} kind={sub.kind} value={item[sub.key] ?? ""} onChange={set} />;
          return <Labeled key={sub.key} label={sub.label} hint={sub.hint}><LeafInput field={sub} value={item[sub.key] ?? ""} onChange={set} /></Labeled>;
        })}
      </div>)}
      <button type="button" className="btn-ghost" disabled={items.length >= field.max} onClick={() => onChange([...items, Object.fromEntries(field.fields.map((sub) => [sub.key, sub.options?.[0]?.[0] ?? ""]))])}>افزودن {field.itemLabel}</button>
    </fieldset>;
  }
  if (field.kind === "image" || field.kind === "video") {
    return <MediaField label={field.label} hint={field.hint} kind={field.kind} value={String(value ?? "")} onChange={onChange} />;
  }
  if (field.kind === "checkbox") {
    return <label className="flex items-center gap-2"><input type="checkbox" checked={value !== false} onChange={(event) => onChange(event.target.checked)} /><span className="label">{field.label}</span></label>;
  }
  if (field.kind === "number") {
    return <Labeled label={field.label} hint={field.hint}><LeafInput field={field} value={String(value ?? "")} onChange={(next) => onChange(next === "" ? "" : Number(next))} /></Labeled>;
  }
  return <Labeled label={field.label} hint={field.hint}><LeafInput field={field} value={String(value ?? "")} onChange={onChange} /></Labeled>;
}

export default function SitePages() {
  const [pages, setPages] = useState<Record<string, PageView> | null>(null);
  const [active, setActive] = useState("about");
  const [draft, setDraft] = useState<Content | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const adopt = useCallback((view: PageView) => {
    setPages((current) => ({ ...(current ?? {}), [view.slug]: view }));
    setDraft(structuredClone(view.content));
  }, []);

  useEffect(() => {
    request<PageView[]>("/v1/admin/site-pages")
      .then((list) => {
        setPages(Object.fromEntries(list.map((view) => [view.slug, view])));
        setDraft(structuredClone(list.find((view) => view.slug === "about")?.content ?? {}));
      })
      .catch((reason) => setError((reason as Error).message));
  }, []);

  const view = pages?.[active];
  const dirty = useMemo(() => !!view && !!draft && JSON.stringify(view.content) !== JSON.stringify(draft), [view, draft]);

  function select(slug: string) {
    if (slug === active) return;
    if (dirty && !window.confirm("تغییرات ذخیره‌نشده از بین می‌رود. ادامه می‌دهید؟")) return;
    setActive(slug);
    setNotice("");
    setError(null);
    setDraft(pages ? structuredClone(pages[slug].content) : null);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      adopt(await request<PageView>(`/v1/admin/site-pages/${active}`, { method: "PUT", body: { content: draft } }));
      setNotice("تغییرات ذخیره شد و همین حالا در سایت نمایش داده می‌شود.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (busy || !window.confirm("محتوای این صفحه به متن پیش‌فرض برمی‌گردد و متن فعلی از بین می‌رود. ادامه می‌دهید؟")) return;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      adopt(await request<PageView>(`/v1/admin/site-pages/${active}`, { method: "DELETE" }));
      setNotice("متن پیش‌فرض بازگردانده شد.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!pages || !draft || !view) return error ? <ErrorBox message={error} /> : <Loading />;
  const schema = SCHEMAS[active];

  return <div className="space-y-5">
    <div><h1 className="text-xl font-bold">صفحه‌های سایت</h1><p className="mt-1 text-sm text-slate-500">متن «درباره ما»، «تماس با ما» و اسناد حقوقی را بدون نیاز به تغییر کد ویرایش کنید. فقط متن ساده پشتیبانی می‌شود.</p></div>
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="صفحه‌ها">
      {ORDER.map((slug) => <button key={slug} type="button" role="tab" aria-selected={slug === active} className={slug === active ? "btn" : "btn-ghost"} onClick={() => select(slug)}>{SCHEMAS[slug].label}{pages[slug].is_default ? "" : " ●"}</button>)}
    </div>
    <section className="card space-y-5" role="tabpanel">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-lg font-bold">{schema.label}</h2><p className="text-xs text-slate-500">{view.is_default ? "در حال نمایش متن پیش‌فرض" : "متن سفارشی منتشر شده است"}{dirty ? " — تغییرات ذخیره‌نشده دارید" : ""}</p></div>
        <code className="text-xs text-slate-500" dir="ltr">{schema.path}</code>
      </div>
      <ErrorBox message={error} />
      {notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
      <form className="space-y-5" onSubmit={save}>
        {schema.fields.map((field) => <FieldEditor key={`${active}-${field.key}`} field={field} value={draft[field.key]} onChange={(next) => setDraft({ ...draft, [field.key]: next })} />)}
        <div className="flex flex-wrap gap-3"><button className="btn" disabled={busy || !dirty}>{busy ? "در حال ذخیره…" : "ذخیره و انتشار"}</button><button type="button" className="btn-ghost" disabled={busy || view.is_default} onClick={reset}>بازگرداندن متن پیش‌فرض</button></div>
      </form>
    </section>
  </div>;
}
