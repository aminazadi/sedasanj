import { useCallback, useEffect, useState } from "react";
import { request } from "../api";
import { ErrorBox, Loading } from "./Widgets";
import { formatBytes } from "../sanitize";

type ErrorInfo = { code: string; message: string; action: string; detail: string };
type Restore = {
  id: string;
  backup_id: string | null;
  status: string;
  live_database: string | null;
  previous_database: string | null;
  verification: { schema_revision?: string; counts?: Record<string, number> };
  error_info: ErrorInfo | null;
  created_at: string;
  applied_at: string | null;
};
type Options = {
  database_name: string | null;
  database_ready: boolean;
  backups: { id: string; completed_at: string; size_bytes: number | null; schema_revision: string | null }[];
  restores: Restore[];
};

const ACTIVE = ["requested", "staging", "apply_requested", "applying"];
const STATUS_LABELS: Record<string, string> = {
  requested: "در صف بازیابی آزمایشی",
  staging: "در حال بازیابی آزمایشی",
  staged: "تأییدشده؛ آمادهٔ جایگزینی",
  apply_requested: "در صف جایگزینی",
  applying: "در حال جایگزینی",
  applied: "جایگزین شد",
  failed: "ناموفق",
  cancelled: "لغو شد",
};
const COUNT_LABELS: Record<string, string> = { users: "کاربران", calls: "تماس‌ها", meetings: "جلسه‌ها", contacts: "مخاطبین" };

function Credentials({ password, totp, setPassword, setTotp }: {
  password: string; totp: string; setPassword: (v: string) => void; setTotp: (v: string) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <input className="input" dir="ltr" type="password" autoComplete="current-password" placeholder="رمز عبور شما" value={password} onChange={(e) => setPassword(e.target.value)} />
      <input className="input" dir="ltr" inputMode="numeric" maxLength={6} placeholder="کد دومرحله‌ای (اگر فعال است)" value={totp} onChange={(e) => setTotp(e.target.value)} />
    </div>
  );
}

export default function TenantRestorePanel({ tenantId, tenantName, onClose }: { tenantId: string; tenantName: string; onClose: () => void }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [confirmName, setConfirmName] = useState("");

  const load = useCallback(async () => {
    try {
      setOptions(await request<Options>(`/v1/admin/tenants/${tenantId}/restore-options`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, [tenantId]);

  useEffect(() => { void load(); }, [load]);
  const polling = options?.restores.some((row) => ACTIVE.includes(row.status)) ?? false;
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [polling, load]);

  async function act(path: string, body?: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      await request(path, { method: "POST", body });
      setPassword("");
      setTotp("");
      setConfirmName("");
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const credentials = { current_password: password, totp_code: totp || null };
  const active = options?.restores.find((row) => ["requested", "staging", "staged", "apply_requested", "applying"].includes(row.status));
  const canSubmit = password.length > 0 && !busy;

  return (
    <section className="card space-y-4" aria-label="بازیابی دیتابیس سازمان">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">بازیابی دیتابیس {tenantName}</h2>
          <p className="text-sm text-slate-500">ابتدا بک‌آپ در یک دیتابیس آزمایشی بازیابی و تأیید می‌شود؛ دیتابیس فعلی تا تأیید نهایی شما دست‌نخورده می‌ماند.</p>
        </div>
        <button className="btn-ghost" type="button" onClick={onClose}>بستن</button>
      </div>
      <ErrorBox message={error} />
      {!options ? <Loading /> : <>
        {!options.database_ready && <p className="text-rose-700">دیتابیس این سازمان آماده نیست؛ بازیابی ممکن نیست.</p>}

        {active ? (
          <div className="space-y-3 rounded border border-slate-200 p-3">
            <div className="font-bold">{STATUS_LABELS[active.status] ?? active.status}</div>
            {active.verification.schema_revision ? (
              <div className="text-sm">
                <div dir="ltr" className="text-left">{active.verification.schema_revision}</div>
                <div>{Object.entries(active.verification.counts ?? {}).map(([name, count]) => `${COUNT_LABELS[name] ?? name}: ${Number(count).toLocaleString("fa-IR")}`).join(" · ")}</div>
              </div>
            ) : null}
            {active.error_info ? (
              <div className="space-y-1 text-sm text-rose-700">
                <div dir="ltr" className="font-mono">{active.error_info.code}</div>
                <div>{active.error_info.message}</div>
                <div className="text-slate-600">{active.error_info.action}</div>
                {active.error_info.detail ? <details><summary className="cursor-pointer">جزئیات فنی</summary><div dir="ltr" className="max-h-32 overflow-auto break-words text-left">{active.error_info.detail}</div></details> : null}
              </div>
            ) : null}
            {active.status === "staged" && (
              <div className="space-y-2">
                <p className="text-sm text-rose-700">با جایگزینی، داده‌هایی که پس از زمان این بک‌آپ ثبت شده‌اند در دیتابیس فعال نخواهند بود (نسخهٔ قبلی با پسوند _pre نگه داشته می‌شود). سازمان در زمان جایگزینی فقط‌خواندنی است.</p>
                <label className="block text-sm">برای تأیید نام دیتابیس را بنویسید: <bdi dir="ltr" className="font-mono">{options.database_name}</bdi></label>
                <input className="input" dir="ltr" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
                <Credentials password={password} totp={totp} setPassword={setPassword} setTotp={setTotp} />
                <button className="btn-primary" type="button" disabled={!canSubmit || confirmName !== options.database_name}
                  onClick={() => void act(`/v1/admin/tenant-restores/${active.id}/apply`, { confirm_database_name: confirmName, ...credentials })}>جایگزینی دیتابیس فعلی</button>
              </div>
            )}
            {["requested", "staging", "staged"].includes(active.status) && (
              <button className="btn-ghost" type="button" disabled={busy} onClick={() => void act(`/v1/admin/tenant-restores/${active.id}/cancel`)}>لغو بازیابی</button>
            )}
            {polling && <Loading />}
          </div>
        ) : options.database_ready && (
          <div className="space-y-3">
            <h3 className="font-bold">انتخاب بک‌آپ</h3>
            {options.backups.length === 0 ? <p className="text-sm text-slate-500">بک‌آپ موفق و منقضی‌نشده‌ای وجود ندارد. ابتدا «پشتیبان‌گیری فوری» بزنید.</p> : <>
              <Credentials password={password} totp={totp} setPassword={setPassword} setTotp={setTotp} />
              <ul className="space-y-2">
                {options.backups.map((backup) => (
                  <li key={backup.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 p-2 text-sm">
                    <span>{new Date(backup.completed_at).toLocaleString("fa-IR")} · {backup.size_bytes ? formatBytes(backup.size_bytes) : "—"} · <bdi dir="ltr">{backup.schema_revision ?? "—"}</bdi></span>
                    <button className="btn-ghost" type="button" disabled={!canSubmit} onClick={() => void act(`/v1/admin/tenants/${tenantId}/restores`, { backup_id: backup.id, ...credentials })}>بازیابی آزمایشی</button>
                  </li>
                ))}
              </ul>
            </>}
          </div>
        )}

        {options.restores.filter((row) => !ACTIVE.includes(row.status) && row.status !== "staged").length > 0 && (
          <div className="space-y-1">
            <h3 className="font-bold">سابقه</h3>
            <ul className="space-y-1 text-sm">
              {options.restores.filter((row) => !ACTIVE.includes(row.status) && row.status !== "staged").map((row) => (
                <li key={row.id}>
                  {new Date(row.created_at).toLocaleString("fa-IR")} — {STATUS_LABELS[row.status] ?? row.status}
                  {row.previous_database ? <> · نسخهٔ قبلی: <bdi dir="ltr" className="font-mono">{row.previous_database}</bdi></> : null}
                  {row.error_info ? <> · <bdi dir="ltr" className="font-mono text-rose-700">{row.error_info.code}</bdi></> : null}
                </li>
              ))}
            </ul>
          </div>
        )}
      </>}
    </section>
  );
}
