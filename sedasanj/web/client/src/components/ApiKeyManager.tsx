import { useEffect, useMemo, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { request } from "../api";
import { freePbxModuleConfig, issabelModuleConfig, pythonAgentConfig } from "../agentConfig";
import type { ApiKey, ApiKeyCreated } from "../types";

type ArchiveFormat = "gzip" | "zip";

const SCOPE_OPTIONS: { value: string; label: string }[] = [
  { value: "ingest:write", label: "ارسال تماس و داخلی‌ها" },
  { value: "module:sync", label: "به‌روزرسانی و گزارش ماژول مرکز تلفن" },
  { value: "crm:write", label: "ثبت نتیجه CRM" },
  { value: "calls:read", label: "خواندن تماس‌ها و نتایج تحلیل" },
  { value: "contacts:read", label: "جست‌وجوی مخاطب با شماره" },
];
const DEFAULT_SCOPES = ["ingest:write", "module:sync"];

function parseCidrs(value: string): string[] {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
}

function toIsoOrNull(value: string): string | null {
  return value ? new Date(`${value}T23:59:59`).toISOString() : null;
}

const PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#$%&()*+,-.:;<=>?@[]^_{|}~";

function strongPassword(): string {
  const bytes = new Uint8Array(64);
  crypto.getRandomValues(bytes);
  const groups = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!#$%&()*+,-.:;<=>?@[]^_{|}~"];
  const required = groups.map((group, index) => group[bytes[index] % group.length]);
  const rest = Array.from(bytes.slice(4, 32), (byte) => PASSWORD_ALPHABET[byte % PASSWORD_ALPHABET.length]);
  const characters = [...required, ...rest];
  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swap = bytes[32 + (index % 32)] % (index + 1);
    [characters[index], characters[swap]] = [characters[swap], characters[index]];
  }
  return characters.join("");
}

function downloadText(filename: string, value: string): void {
  const url = URL.createObjectURL(new Blob([value], { type: "text/plain;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ApiKeyManager({ keys, reload }: { keys: ApiKey[]; reload: () => Promise<void> }) {
  const [label, setLabel] = useState("");
  const [format, setFormat] = useState<ArchiveFormat>("gzip");
  const [protectedZip, setProtectedZip] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [confirmedCopy, setConfirmedCopy] = useState(false);
  const [created, setCreated] = useState<{ id: string; prefix: string; secret: string; archiveFormat: ArchiveFormat; password: string; title: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [exporting, setExporting] = useState<ApiKey | null>(null);
  const [exportSecret, setExportSecret] = useState("");
  const [exportPassword, setExportPassword] = useState("");
  const [editLabel, setEditLabel] = useState("");
  const [scopes, setScopes] = useState<string[]>(DEFAULT_SCOPES);
  const [expiresOn, setExpiresOn] = useState("");
  const [cidrText, setCidrText] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => setCreated(null), []);
  const editingKey = keys.find((item) => item.id === editing);
  const keepingExistingPassword = Boolean(
    editingKey?.archive_format === "zip"
      && editingKey.archive_password_configured
      && format === "zip"
      && protectedZip
      && !password,
  );
  const passwordValid = !protectedZip
    || keepingExistingPassword
    || (password.length >= 12 && password.length <= 128 && password === confirmation);
  const maySubmit = passwordValid && (!generated || confirmedCopy);
  const configs = useMemo(
    () => created ? {
      python: pythonAgentConfig(window.location.origin, created.secret, created.archiveFormat, created.password),
      freepbx: freePbxModuleConfig(window.location.origin, created.id, created.prefix, created.secret, created.archiveFormat, created.password),
    } : null,
    [created],
  );

  function resetSecretFields(): void {
    setPassword("");
    setConfirmation("");
    setGenerated(false);
    setConfirmedCopy(false);
    setShowPassword(false);
  }

  function generate(): void {
    const value = strongPassword();
    setPassword(value);
    setConfirmation(value);
    setGenerated(true);
    setConfirmedCopy(false);
    setShowPassword(true);
  }

  async function copyPassword(): Promise<void> {
    await navigator.clipboard.writeText(password);
    setConfirmedCopy(true);
  }

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    try {
      const archivePassword = format === "zip" && protectedZip ? password : null;
      const key = await request<ApiKeyCreated>("/v1/auth/api-keys", {
        method: "POST",
        body: {
          label: label || null,
          archive_format: format,
          archive_password: archivePassword,
          scopes,
          expires_at: toIsoOrNull(expiresOn),
          allowed_cidrs: parseCidrs(cidrText),
        },
      });
      setCreated({ id: key.id, prefix: key.key_prefix, secret: key.secret, archiveFormat: key.archive_format === "zip" ? "zip" : "gzip", password: archivePassword ?? "", title: "اطلاعات یک‌باره اتصال" });
      setLabel("");
      setScopes(DEFAULT_SCOPES);
      setExpiresOn("");
      setCidrText("");
      resetSecretFields();
      await reload();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  async function updateKey(key: ApiKey, nextFormat: ArchiveFormat): Promise<void> {
    setError(null);
    try {
      const archivePassword = nextFormat === "zip" && protectedZip && password ? password : undefined;
      await request<ApiKey>(`/v1/auth/api-keys/${key.id}`, {
        method: "PATCH",
        body: {
          label: editLabel || null,
          archive_format: nextFormat,
          archive_password: archivePassword,
          remove_archive_password: nextFormat === "gzip" || (nextFormat === "zip" && !protectedZip),
          scopes,
          expires_at: toIsoOrNull(expiresOn),
          allowed_cidrs: parseCidrs(cidrText),
        },
      });
      setEditing(null);
      resetSecretFields();
      await reload();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  async function rotateKey(key: ApiKey): Promise<void> {
    setError(null);
    try {
      const next = await request<ApiKeyCreated>(`/v1/auth/api-keys/${key.id}/rotate?grace_hours=24`, { method: "POST" });
      setCreated({ id: next.id, prefix: next.key_prefix, secret: next.secret, archiveFormat: next.archive_format === "zip" ? "zip" : "gzip", password: "", title: "کلید جایگزین؛ کلید قبلی تا ۲۴ ساعت دیگر معتبر است" });
      await reload();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  async function validateAndDownloadExisting(product: "freepbx" | "issabel" = "freepbx"): Promise<void> {
    if (!exporting || !exportSecret) return;
    setError(null);
    try {
      const headers: Record<string, string> = { Authorization: `Bearer ${exportSecret}` };
      if (exportPassword) headers["X-CBI-Archive-Password"] = exportPassword;
      const response = await fetch("/v1/ingest/config/validate", { method: "POST", headers });
      if (!response.ok) throw new Error("کلید، رمز ZIP یا تنظیم transport معتبر نیست.");
      const validation = await response.json() as { archive_format: string; archive_password_configured: boolean; archive_password_valid: boolean };
      if (validation.archive_format !== exporting.archive_format
        || validation.archive_password_configured !== exporting.archive_password_configured
        || !validation.archive_password_valid) {
        throw new Error("تنظیمات واردشده با کلید ذخیره‌شده مطابقت ندارد.");
      }
      downloadText(
        product === "issabel" ? "sedasanj-issabel-config.json" : "sedasanj-freepbx-config.json",
        (product === "issabel" ? issabelModuleConfig : freePbxModuleConfig)(window.location.origin, exporting.id, exporting.key_prefix, exportSecret, exporting.archive_format, exportPassword),
      );
      setExportSecret("");
      setExportPassword("");
      setExporting(null);
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  return (
    <div className="card space-y-4">
      <div>
        <h2 className="font-bold">کلیدهای API و فرمت فایل</h2>
        <p className="mt-1 text-sm text-slate-500">هر کلید فرمت ورودی مستقل دارد. رمز ZIP پس از ثبت قابل بازیابی نیست.</p>
      </div>
      {error ? <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</div> : null}
      {created ? (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm">
          <div className="font-bold text-amber-900">{created.title}</div>
          <p className="my-2 text-amber-800">این اطلاعات را اکنون کپی یا فایل تنظیمات را دانلود کنید.</p>
          <div className="space-y-2" dir="ltr">
            <code className="block break-all rounded bg-white p-2">{created.secret}</code>
            {created.password ? <code className="block break-all rounded bg-white p-2">{created.password}</code> : null}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn" onClick={() => configs && downloadText("sedasanj-freepbx-config.json", configs.freepbx)}>دانلود تنظیمات FreePBX</button>
            <button className="btn" onClick={() => created && downloadText("sedasanj-issabel-config.json", issabelModuleConfig(window.location.origin, created.id, created.prefix, created.secret, created.archiveFormat, created.password))}>دانلود تنظیمات ایزابل</button>
            <button className="btn-ghost" onClick={() => configs && downloadText("cbi-agent.toml", configs.python)}>دانلود تنظیمات Python Agent</button>
            <button className="btn-ghost" onClick={() => configs && void navigator.clipboard.writeText(configs.freepbx)}>کپی تنظیمات FreePBX</button>
            <button className="btn-ghost" onClick={() => setCreated(null)}>بستن و پاک‌کردن</button>
          </div>
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="table min-w-[900px]">
          <thead><tr><th>پیشوند</th><th>برچسب</th><th>فرمت</th><th>رمز ZIP</th><th>دسترسی‌ها</th><th>انقضا</th><th>آخرین استفاده</th><th /></tr></thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.id}>
                <td dir="ltr">{key.key_prefix}…</td><td>{key.label ?? "—"}</td>
                <td>{key.archive_format === "wav" ? "WAV قدیمی" : key.archive_format.toUpperCase()}</td>
                <td>{key.archive_password_configured ? "فعال" : "بدون رمز"}</td>
                <td dir="ltr">{key.scopes.join(", ")}{key.allowed_cidrs.length ? ` · IP: ${key.allowed_cidrs.join(", ")}` : ""}</td>
                <td>{key.expires_at ? new Date(key.expires_at).toLocaleDateString("fa-IR") : "بدون انقضا"}</td>
                <td>{key.last_used_at ? new Date(key.last_used_at).toLocaleString("fa-IR") : "—"}</td>
                <td className="space-x-1 space-x-reverse whitespace-nowrap">
                  <button className="btn-ghost text-xs" onClick={() => { setEditing(key.id); setEditLabel(key.label ?? ""); setScopes(key.scopes); setExpiresOn(key.expires_at ? key.expires_at.slice(0, 10) : ""); setCidrText(key.allowed_cidrs.join("\n")); setFormat(key.archive_format === "zip" ? "zip" : "gzip"); setProtectedZip(key.archive_password_configured); resetSecretFields(); }}>ویرایش</button>
                  <button className="btn-ghost text-xs" onClick={() => { setExporting(key); setExportSecret(""); setExportPassword(""); }}>فایل FreePBX</button>
                  <button className="btn-ghost text-xs" onClick={() => void rotateKey(key)}>چرخش کلید</button>
                  <button className="btn-ghost text-xs text-rose-700" onClick={async () => { await request<void>(`/v1/auth/api-keys/${key.id}`, { method: "DELETE" }); await reload(); }}>لغو</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {exporting ? (
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <div className="mb-1 font-medium">ساخت فایل تنظیمات مرکز تلفن برای {exporting.key_prefix}…</div>
          <p className="mb-3 text-xs text-slate-600">secret فعلی فقط برای اعتبارسنجی مستقیم کلید استفاده می‌شود و در حساب شما ذخیره یا بازیابی نمی‌شود.</p>
          <div className="grid gap-2 md:grid-cols-2">
            <input className="input" dir="ltr" type="password" value={exportSecret} onChange={(event) => setExportSecret(event.target.value)} placeholder="sk_live_…" autoComplete="off" />
            {exporting.archive_password_configured ? <input className="input" dir="ltr" type="password" value={exportPassword} onChange={(event) => setExportPassword(event.target.value)} placeholder="رمز فعلی ZIP" autoComplete="off" /> : <div />}
          </div>
          <div className="mt-3 flex gap-2"><button className="btn" disabled={!exportSecret || (exporting.archive_password_configured && !exportPassword)} onClick={() => void validateAndDownloadExisting()}>دانلود FreePBX</button><button className="btn" disabled={!exportSecret || (exporting.archive_password_configured && !exportPassword)} onClick={() => void validateAndDownloadExisting("issabel")}>دانلود ایزابل</button><button className="btn-ghost" onClick={() => { setExporting(null); setExportSecret(""); setExportPassword(""); }}>انصراف</button></div>
        </div>
      ) : null}
      {editing ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 font-medium">ویرایش کلید</div>
          <label className="mb-3 block"><span className="label">برچسب کلید</span><input className="input" value={editLabel} onChange={(event) => setEditLabel(event.target.value)} placeholder="مثلاً مرکز تماس تهران" /></label>
          <AccessFields scopes={scopes} setScopes={setScopes} expiresOn={expiresOn} setExpiresOn={setExpiresOn} cidrText={cidrText} setCidrText={setCidrText} />
          <ArchiveFields format={format} setFormat={setFormat} protectedZip={protectedZip} setProtectedZip={setProtectedZip} password={password} setPassword={setPassword} confirmation={confirmation} setConfirmation={setConfirmation} showPassword={showPassword} setShowPassword={setShowPassword} generated={generated} confirmedCopy={confirmedCopy} generate={generate} copyPassword={copyPassword} passwordOptional={keepingExistingPassword} />
          <div className="mt-3 flex gap-2"><button className="btn" disabled={!maySubmit || scopes.length === 0} onClick={() => void updateKey(keys.find((item) => item.id === editing)!, format)}>ذخیره تغییرات</button><button className="btn-ghost" onClick={() => { setEditing(null); resetSecretFields(); }}>انصراف</button></div>
        </div>
      ) : (
        <form className="space-y-3 border-t border-slate-100 pt-4" onSubmit={submit}>
          <div className="grid gap-3 md:grid-cols-2"><label><span className="label">برچسب کلید</span><input className="input" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="مثلاً مرکز تماس تهران" /></label><ArchiveFields format={format} setFormat={setFormat} protectedZip={protectedZip} setProtectedZip={setProtectedZip} password={password} setPassword={setPassword} confirmation={confirmation} setConfirmation={setConfirmation} showPassword={showPassword} setShowPassword={setShowPassword} generated={generated} confirmedCopy={confirmedCopy} generate={generate} copyPassword={copyPassword} /></div>
          <AccessFields scopes={scopes} setScopes={setScopes} expiresOn={expiresOn} setExpiresOn={setExpiresOn} cidrText={cidrText} setCidrText={setCidrText} />
          <button className="btn" disabled={!maySubmit || scopes.length === 0}>ایجاد کلید جدید</button>
        </form>
      )}
    </div>
  );
}

type ArchiveFieldsProps = {
  format: ArchiveFormat; setFormat: (value: ArchiveFormat) => void; protectedZip: boolean; setProtectedZip: (value: boolean) => void;
  password: string; setPassword: (value: string) => void; confirmation: string; setConfirmation: (value: string) => void;
  showPassword: boolean; setShowPassword: (value: boolean) => void; generated: boolean; confirmedCopy: boolean;
  generate: () => void; copyPassword: () => Promise<void>; passwordOptional?: boolean;
};

function ArchiveFields(props: ArchiveFieldsProps) {
  return <div className="space-y-3 md:col-span-2">
    <label><span className="label">فرمت ارسالی agent</span><select className="input" value={props.format} onChange={(event) => { const value = event.target.value as ArchiveFormat; props.setFormat(value); if (value === "gzip") props.setProtectedZip(false); }}><option value="gzip">GZIP — سریع و بدون رمز</option><option value="zip">ZIP — با امکان رمز AES-256</option></select></label>
    {props.format === "zip" ? <><ToggleSwitch checked={props.protectedZip} onChange={props.setProtectedZip} label="ZIP با رمز AES-256" labelClassName="text-sm" />{props.protectedZip ? <div className="grid gap-2 md:grid-cols-2">{props.passwordOptional ? <p className="text-xs text-slate-500 md:col-span-2">برای حفظ رمز فعلی، فیلدها را خالی بگذارید.</p> : null}<input className="input" dir="ltr" type={props.showPassword ? "text" : "password"} minLength={12} maxLength={128} value={props.password} onChange={(event) => props.setPassword(event.target.value)} placeholder={props.passwordOptional ? "رمز جدید (اختیاری)" : "رمز ۱۲ تا ۱۲۸ کاراکتر"} /><input className="input" dir="ltr" type={props.showPassword ? "text" : "password"} value={props.confirmation} onChange={(event) => props.setConfirmation(event.target.value)} placeholder="تکرار رمز" /><div className="flex flex-wrap gap-2 md:col-span-2"><button type="button" className="btn-ghost" onClick={props.generate}>تولید رمز قوی</button><button type="button" className="btn-ghost" onClick={() => void props.copyPassword()} disabled={!props.password}>کپی رمز</button><button type="button" className="btn-ghost" onClick={() => props.setShowPassword(!props.showPassword)}>{props.showPassword ? "مخفی‌کردن" : "نمایش رمز"}</button></div>{props.generated && !props.confirmedCopy ? <p className="text-xs text-amber-700 md:col-span-2">برای فعال‌شدن ذخیره، رمز تولیدشده را کپی کنید.</p> : null}</div> : null}</> : null}
  </div>;
}

type AccessFieldsProps = {
  scopes: string[]; setScopes: (value: string[]) => void; expiresOn: string; setExpiresOn: (value: string) => void;
  cidrText: string; setCidrText: (value: string) => void;
};

function AccessFields(props: AccessFieldsProps) {
  return <div className="space-y-3">
    <div className="space-y-2">
      <span className="label">دسترسی‌های کلید</span>
      {SCOPE_OPTIONS.map((option) => (
        <ToggleSwitch
          key={option.value}
          checked={props.scopes.includes(option.value)}
          onChange={(on) => props.setScopes(on ? [...props.scopes, option.value] : props.scopes.filter((item) => item !== option.value))}
          label={option.label}
          labelClassName="text-sm"
        />
      ))}
    </div>
    <div className="grid gap-3 md:grid-cols-2">
      <label><span className="label">تاریخ انقضا (اختیاری)</span><input className="input" type="date" dir="ltr" value={props.expiresOn} min={new Date().toISOString().slice(0, 10)} onChange={(event) => props.setExpiresOn(event.target.value)} /></label>
      <label><span className="label">IPهای مجاز (اختیاری، هر خط یک آدرس یا CIDR)</span><textarea className="input" dir="ltr" rows={2} value={props.cidrText} onChange={(event) => props.setCidrText(event.target.value)} placeholder="203.0.113.10" /></label>
    </div>
  </div>;
}
