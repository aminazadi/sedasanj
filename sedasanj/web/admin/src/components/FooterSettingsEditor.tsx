import { isSafeFooterUrl, type FooterSettings, type FooterLink } from "../../../shared/lib/siteFooter";

export default function FooterSettingsEditor({ value, onChange }: { value: FooterSettings; onChange: (value: FooterSettings) => void }) {
  function linksEditor(key: "links" | "legal_links", title: string) {
    const links = value[key];
    function update(index: number, patch: Partial<FooterLink>) {
      onChange({ ...value, [key]: links.map((link, i) => i === index ? { ...link, ...patch } : link) });
    }
    function move(index: number, offset: number) {
      const next = [...links];
      [next[index], next[index + offset]] = [next[index + offset], next[index]];
      onChange({ ...value, [key]: next });
    }
    return <fieldset className="space-y-3 border border-slate-200 p-4">
      <legend className="px-2">{title}</legend>
      {links.map((link, index) => <div key={index} className="space-y-2 border-b border-slate-200 pb-3">
        <label className="block"><span className="label">عنوان لینک {index + 1}</span><input className="input" required maxLength={120} value={link.label} onChange={(event) => update(index, { label: event.target.value })}/></label>
        <label className="block"><span className="label">نشانی لینک {index + 1}</span><input className="input" required dir="ltr" maxLength={2048} value={link.url} placeholder="/about یا https://example.com" onChange={(event) => { event.target.setCustomValidity(""); update(index, { url: event.target.value }); }} onInvalid={(event) => event.currentTarget.setCustomValidity("نشانی داخلی با / یا نشانی کامل با https:// یا http:// وارد کنید.")} onBlur={(event) => event.currentTarget.setCustomValidity(isSafeFooterUrl(link.url) ? "" : "نشانی داخلی با / یا نشانی کامل با https:// یا http:// وارد کنید.")}/></label>
        <div className="flex flex-wrap gap-2">
          <button className="btn" type="button" disabled={index === 0} onClick={() => move(index, -1)} aria-label={`انتقال لینک ${index + 1} به بالا`}>بالا</button>
          <button className="btn" type="button" disabled={index === links.length - 1} onClick={() => move(index, 1)} aria-label={`انتقال لینک ${index + 1} به پایین`}>پایین</button>
          <button className="btn" type="button" onClick={() => onChange({ ...value, [key]: links.filter((_, i) => i !== index) })}>حذف لینک</button>
        </div>
      </div>)}
      <button className="btn" type="button" disabled={links.length >= 30} onClick={() => onChange({ ...value, [key]: [...links, { label: "", url: "" }] })}>افزودن لینک</button>
    </fieldset>;
  }
  const fields = [
    ["contact_title", "عنوان بخش تماس", 200],
    ["contact_description", "توضیحات بخش تماس", 2000],
    ["description", "توضیحات معرفی", 4000],
    ["links_title", "عنوان لینک‌های پرکاربرد", 200],
    ["trust_title", "عنوان نمادها", 200],
    ["copyright", "متن پایین فوتر", 500],
  ] as const;
  return <div className="space-y-5">
    <h3 className="text-lg">محتوای فوتر</h3>
    {fields.map(([key, label, limit]) => <label key={key} className="block"><span className="label">{label}</span><textarea className="input" maxLength={limit} value={value[key]} onChange={(event) => onChange({ ...value, [key]: event.target.value })}/></label>)}
    {linksEditor("links", "لینک‌های پرکاربرد")}
    {linksEditor("legal_links", "لینک‌های قوانین و حریم خصوصی")}
  </div>;
}
