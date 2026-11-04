import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { Icon, type IconifyIcon } from "@iconify/react";
import calendarClockIcon from "@iconify-icons/lucide/calendar-clock";
import databaseIcon from "@iconify-icons/lucide/database";
import downloadIcon from "@iconify-icons/lucide/download";
import fileUpIcon from "@iconify-icons/lucide/file-up";
import historyIcon from "@iconify-icons/lucide/history";
import keyRoundIcon from "@iconify-icons/lucide/key-round";
import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { downloadFile, fmt, query, request } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { ErrorBox, Pagination } from "../components/Widgets";
import { useTablePageSize } from "../lib/useTablePagination";
import "./organization-data.css";

const API = "/v1/account/data";
const DAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"];
const KINDS = { manual: "بک‌آپ دستی", scheduled: "بک‌آپ زمان‌بندی‌شده", import: "بازیابی" };
const STATES: Record<string, string> = {
  uploading: "در انتظار فایل", queued: "در صف", running: "در حال اجرا", review: "آمادهٔ بررسی",
  succeeded: "آماده", failed: "ناموفق", expired: "منقضی",
};
const TABLE_LABELS: Record<string, string> = {
  audio_objects: "فایل‌های صوتی", calls: "تماس‌ها", contacts: "مخاطبان", pbx_extensions: "داخلی‌ها",
  teams: "تیم‌ها", team_memberships: "اعضای تیم", call_operator_assignments: "تخصیص اپراتورها",
  utterances: "قطعه‌های گفتار", transcripts: "متن تماس‌ها", asr_transcript_revisions: "نسخه‌های تشخیص گفتار",
  asr_transcript_revision_segments: "بخش‌های تشخیص گفتار", transcript_revisions: "نسخه‌های متن",
  transcript_revision_segments: "بخش‌های نسخهٔ متن", analysis_runs: "تحلیل تماس‌ها",
  analysis_steps: "مراحل تحلیل", call_insights: "خلاصهٔ تماس‌ها", sales_insights: "بینش فروش",
  kpi_configurations: "تنظیمات KPI", kpi_goals: "اهداف KPI", crm_outcomes: "نتایج فروش",
  operator_score_rubrics: "معیارهای امتیاز", operator_call_scores: "امتیاز تماس",
  operator_call_coachings: "بازخورد مربی", call_knowledge: "دانش تماس",
  chat_conversations: "گفتگوهای دستیار", chat_messages: "پیام‌های دستیار", assistant_exports: "فایل‌های دستیار",
  assistant_tool_runs: "خروجی ابزارهای دستیار", organization_memories: "حافظهٔ سازمان", follow_up_tasks: "وظایف", follow_up_task_events: "رویدادهای وظیفه",
  meetings: "جلسات", meeting_chunks: "قطعه‌های صوت جلسه", meeting_segments: "بخش‌های متن جلسه",
  meeting_chunk_speakers: "گویندگان قطعه", meeting_speakers: "گویندگان جلسه",
  meeting_analysis_steps: "مراحل تحلیل جلسه", meeting_minutes: "صورت‌جلسه‌ها",
  meeting_events: "رویدادهای جلسه", tenant_ai_instructions: "دستورهای هوش مصنوعی",
  scheduled_reports: "تعریف گزارش‌ها", scheduled_report_runs: "گزارش‌های آرشیوشده",
};
const ERRORS: Record<string, string> = {
  org_archive_invalid: "فایل اصلی و کلید همان بک‌آپ را دوباره بررسی کنید.",
  org_archive_too_large: "حجم فایل از سقف مجاز بیشتر است.",
  org_archive_unavailable: "فضای ذخیره‌سازی و تنظیمات سامانه را بررسی کنید.",
  org_archive_review_changed: "مقصد تغییر کرده است. پیش‌نمایش جدید را بررسی کنید.",
  org_archive_mapping: "اعضای مقصد تغییر کرده‌اند. نگاشت را دوباره انتخاب کنید.",
  org_backup_destination: "میزبان، مسیر و نوع اتصال را بررسی کنید.",
  org_backup_ftp_failed: "مسیر، مجوز نوشتن و گواهی مقصد را بررسی کنید.",
  forbidden: "دسترسی مدیر سازمان را بررسی کنید.",
};

type Kind = keyof typeof KINDS;
type Count = { new: number; duplicate: number; skipped: number };
type Owner = { id: string; label: string; fallback: number; target: string; explicit: boolean };
type Member = { id: string; label: string; role: string };
type Destination = {
  protocol: "ftp" | "ftps"; host: string; port: number; directory: string; username: string;
};
type Settings = {
  enabled: boolean; cadence: "daily" | "weekly"; local_time: string; weekday: number;
  destination: Partial<Destination>; timezone: string; next_run_at: string | null;
  has_password: boolean; has_recovery_key: boolean; allow_plain_ftp: boolean; max_bytes: number;
};
type Run = {
  id: string; kind: Kind; phase: string; state: string; transfer_state: string | null;
  transfer_attempts: number; next_attempt_at: string | null; error_code: string | null;
  size_bytes: number | null; checksum: string | null; created_at: string; expires_at: string;
  can_review: boolean; can_upload: boolean; can_download: boolean;
  summary: { counts?: Record<string, Count | number>; owners?: Owner[]; omitted?: Record<string, number> };
};

const EMPTY_DESTINATION: Destination = { protocol: "ftps", host: "", port: 21, directory: "/", username: "" };

function fileSize(bytes: number) {
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  const power = Math.min(3, Math.max(0, Math.floor(Math.log(Math.max(1, bytes)) / Math.log(1024))));
  return `${fmt.decimal(bytes / 1024 ** power, 1)} ${units[power]}`;
}

function scheduledTime(iso: string, timezone: string) {
  return new Date(iso).toLocaleString("fa-IR-u-ca-persian", {
    dateStyle: "short", timeStyle: "short", timeZone: timezone,
  });
}

function recoveryKey() {
  const bytes = window.crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function Card({ title, icon, children }: { title: string; icon: IconifyIcon; children: ReactNode }) {
  return <section className="org-data-card">
    <h2 className="org-data-heading"><Icon icon={icon} aria-hidden="true" />{title}</h2>
    {children}
  </section>;
}

function DataSkeleton() {
  return <div className="org-data-grid" role="status" aria-label="در حال بارگذاری داده‌های سازمان">
    {[0, 1].map((item) => <div className="org-data-card" key={item}>
      <div className="org-data-heading"><span className="org-data-skeleton w-36" /></div>
      <div className="org-data-body space-y-4">
        <span className="org-data-skeleton w-4/5" /><span className="org-data-skeleton h-16 w-full" />
        <span className="org-data-skeleton h-10 w-2/3" />
      </div>
    </div>)}
    <div className="org-data-card org-data-wide org-data-body"><span className="org-data-skeleton h-20 w-full" /></div>
  </div>;
}

function State({ value }: { value: string }) {
  return <span className={`org-data-status org-data-status--${value}`}>{STATES[value] ?? value}</span>;
}

function Review({
  run, members, busy, onMap, onConfirm, onCancel,
}: {
  run: Run; members: Member[]; busy: boolean;
  onMap: (mapping: Record<string, string>) => void; onConfirm: () => void; onCancel: () => void;
}) {
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const changed = Object.keys(mapping).length > 0;
  const rows = Object.entries(run.summary.counts ?? {}).flatMap(([name, count]) =>
    typeof count !== "number" && (count.new || count.duplicate || count.skipped) ? [{ name, ...count }] : []);
  const totals = rows.reduce((total, row) => ({
    new: total.new + row.new, duplicate: total.duplicate + row.duplicate, skipped: total.skipped + row.skipped,
  }), { new: 0, duplicate: 0, skipped: 0 });

  return <div className="org-data-review">
    <h3 className="font-bold">پیش‌نمایش بازیابی</h3>
    <dl className="org-data-counts">
      {([["new", "آمادهٔ ورود"], ["duplicate", "تکراری"], ["skipped", "ناسازگار"]] as const).map(([key, label]) =>
        <div key={key}><dt>{label}</dt><dd>{fmt.int(totals[key])}</dd></div>)}
    </dl>
    {rows.length > 0 && <details>
      <summary className="cursor-pointer font-medium">جزئیات رکوردها</summary>
      <div className="overflow-x-auto">
        <table className="table"><thead><tr><th>داده</th><th>جدید</th><th>تکراری</th><th>ناسازگار</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.name}>
            <th scope="row">{TABLE_LABELS[row.name] ?? row.name}</th><td>{fmt.int(row.new)}</td>
            <td>{fmt.int(row.duplicate)}</td><td>{fmt.int(row.skipped)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>}
    {(run.summary.owners?.length ?? 0) > 0 && <details>
      <summary className="cursor-pointer font-medium">نگاشت اعضای مبدأ</summary>
      <p className="org-data-muted">مالکیت موارد بدون نگاشت به مدیر واردکننده می‌رسد. نقش‌های اپراتوری به نگاشت یک اپراتور نیاز دارند.</p>
      <div className="org-data-mappings">{run.summary.owners?.map((owner) => <label key={owner.id}>
        <span dir="ltr" className="break-all">{owner.label}</span>
        <select aria-label={`نگاشت ${owner.label}`} value={mapping[owner.id] ?? (owner.explicit ? owner.target : "")}
          disabled={busy || !members.length}
          onChange={(event) => setMapping({ ...mapping, [owner.id]: event.target.value })}>
          <option value="">بدون نگاشت دستی</option>
          {owner.explicit && !members.some((member) => member.id === owner.target) &&
            <option value={owner.target}>عضو در دسترس نیست</option>}
          {members.map((member) => <option value={member.id} key={member.id}>{member.label}</option>)}
        </select>
        {owner.fallback > 0 && <small>{fmt.int(owner.fallback)} انتساب به مدیر واردکننده</small>}
      </label>)}</div>
    </details>}
    <div className="org-data-actions">
      {changed ? <button className="btn" type="button" disabled={busy}
        onClick={() => onMap(Object.fromEntries((run.summary.owners ?? [])
          .map((owner) => [owner.id, mapping[owner.id] ?? (owner.explicit ? owner.target : "")])
          .filter(([, target]) => target)))}>به‌روزرسانی پیش‌نمایش</button>
        : <button className="btn" type="button" disabled={busy || run.error_code === "org_archive_mapping"}
          onClick={onConfirm}>تأیید ورود داده‌ها</button>}
      <button className="btn-ghost" type="button" disabled={busy} onClick={onCancel}>لغو بازیابی</button>
    </div>
  </div>;
}

export default function OrganizationData() {
  const [params, setParams] = useSearchParams();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [destination, setDestination] = useState<Destination>(EMPTY_DESTINATION);
  const [ftpPassword, setFtpPassword] = useState("");
  const [pendingKey, setPendingKey] = useState("");
  const [importKey, setImportKey] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<{ items: Run[]; total: number }>({ items: [], total: 0 });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<"apply" | "delete" | "rotate" | null>(null);
  const [limit] = useTablePageSize();
  const [refreshVersion, setRefreshVersion] = useState(0);

  const requestedRun = params.get("archive_run");
  const runId = requestedRun && /^[a-f0-9-]{36}$/i.test(requestedRun) ? requestedRun : null;
  const requestedKind = params.get("archive_kind") ?? "";
  const requestedState = params.get("archive_state") ?? "";
  const kind = Object.hasOwn(KINDS, requestedKind) ? requestedKind : "";
  const state = ["active", "review", "succeeded", "failed", "expired"].includes(requestedState) ? requestedState : "";
  const rawOffset = Number(params.get("archive_offset"));
  const offset = Number.isInteger(rawOffset) && rawOffset > 0 && rawOffset <= 10000 ? rawOffset : 0;

  function changeQuery(values: Record<string, string | null>) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
      return next;
    }, { replace: true });
  }

  const loadSettings = useCallback(async () => {
    try {
      const value = await request<Settings>(`${API}/backup/settings`);
      setSettings(value);
      setForm(value);
      setDestination({ ...EMPTY_DESTINATION, ...value.destination });
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => { void loadSettings(); }, [loadSettings]);

  const nextRunAt = settings?.next_run_at;
  useEffect(() => {
    if (!nextRunAt) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      if (document.hidden || Date.now() < Date.parse(nextRunAt)) return;
      void request<Settings>(`${API}/backup/settings`).then((value) => {
        if (!stopped) setSettings(value);
      }).catch(() => undefined);
    }, 30_000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [nextRunAt]);

  useEffect(() => {
    let stopped = false;
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const page = await request<{ items: Run[]; total: number }>(`${API}/runs${query({
          limit, offset, kind, state,
        })}`);
        const current = runId ? await request<Run>(`${API}/runs/${runId}`) : null;
        if (!stopped) { setHistory(page); setActiveRun(current); }
      } catch (cause) {
        if (!stopped) setError((cause as Error).message);
      } finally { pending = false; }
    }
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [kind, state, limit, offset, runId, refreshVersion]);

  const reviewId = activeRun?.can_review ? activeRun.id : null;
  useEffect(() => {
    if (!reviewId) return;
    let stopped = false;
    void request<Member[]>(`${API}/import/members`).then((result) => {
      if (!stopped) setMembers(result);
    }).catch((cause: Error) => { if (!stopped) setError(cause.message); });
    return () => { stopped = true; };
  }, [reviewId]);

  async function act(action: string, perform: () => Promise<void>, success?: string) {
    setBusy(action);
    setNotice("");
    setError(null);
    try {
      await perform();
      if (success) setNotice(success);
      setRefreshVersion((version) => version + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function saveSettings(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    void act("settings", async () => {
      const value = await request<Settings>(`${API}/backup/settings`, { method: "PUT", body: {
        ...form, destination: destination.host ? { ...destination, password: ftpPassword || null } : null,
      } });
      setSettings(value);
      setForm(value);
      setFtpPassword("");
    }, "تنظیمات بک‌آپ ذخیره شد.");
  }

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !settings) return;
    if (file.size > settings.max_bytes) {
      setError(`حجم فایل باید حداکثر ${fileSize(settings.max_bytes)} باشد.`);
      return;
    }
    const selected = file;
    void act("upload", async () => {
      const run = activeRun?.can_upload ? activeRun : await request<Run>(`${API}/import`, {
        method: "POST", body: { key: importKey.trim() },
      });
      setActiveRun(run);
      setImportKey("");
      changeQuery({ archive_run: run.id });
      const queued = await request<Run>(`${API}/import/${run.id}/file`, { method: "PUT", body: selected });
      setActiveRun(queued);
      setFile(null);
      (document.getElementById("org-data-file") as HTMLInputElement | null)?.form?.reset();
    }, "فایل دریافت شد و در صف بررسی قرار گرفت.");
  }

  function download(run: Run) {
    void act("download", async () => {
      const url = `${API}/runs/${run.id}/download`;
      await request<void>(url, { method: "POST" });
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    });
  }

  if (!form || !settings) return error
    ? <div className="space-y-3"><ErrorBox message={error} />
      <button className="btn-ghost" onClick={() => { setError(null); void loadSettings(); }}>تلاش دوباره</button></div>
    : <DataSkeleton />;

  const current = activeRun?.kind === "import" ? activeRun : null;
  const selectedBusy = current?.state === "queued" || current?.state === "running";

  return <div className="org-data-grid" dir="rtl">
    {(error || notice) && <div className="org-data-wide" aria-live="polite">
      <ErrorBox message={error} />{notice && <p className="org-data-notice" role="status">{notice}</p>}
    </div>}
    <Card title="خروجی و بازیابی" icon={databaseIcon}>
      <div className="org-data-body">
        <p className="org-data-muted">یک فایل رمزگذاری‌شده از داده‌های کاری سازمان بگیرید یا فایل موجود را بازیابی کنید.</p>
        <div className="org-data-actions">
          <button className="btn" type="button" disabled={!!busy || !settings.has_recovery_key}
            onClick={() => void act("backup", async () => {
              const run = await request<Run>(`${API}/backup`, { method: "POST" });
              changeQuery({ archive_run: run.id, archive_kind: null, archive_state: null, archive_offset: null });
            }, "بک‌آپ در صف آماده‌سازی است. فایل را پس از آماده‌شدن از تاریخچه دریافت کنید.")}>
            <Icon icon={downloadIcon} aria-hidden="true" /> ساخت بک‌آپ باینری
          </button>
          <button className="btn-ghost" type="button" disabled={!!busy}
            onClick={() => settings.has_recovery_key ? setDialog("rotate") : setPendingKey(recoveryKey())}>
            <Icon icon={keyRoundIcon} aria-hidden="true" />
            {settings.has_recovery_key ? "تولید کلید جدید" : "ساخت کلید بازیابی"}
          </button>
        </div>
        {!settings.has_recovery_key && !pendingKey && <p className="org-data-muted">برای ساخت اولین بک‌آپ، کلید بازیابی بسازید.</p>}
        {pendingKey && <div className="org-data-review">
          <h3 className="font-bold">کلید بازیابی</h3>
          <p className="org-data-muted">کلید را در محل امنی جدا از فایل ذخیره کنید. پس از ثبت، دوباره نمایش داده نمی‌شود.</p>
          <input aria-label="کلید تولیدشده" className="input w-full font-mono" dir="ltr" value={pendingKey} readOnly />
          <div className="org-data-actions">
            <button className="btn-ghost" type="button" disabled={!!busy}
              onClick={() => void act("copy", () => navigator.clipboard.writeText(pendingKey), "کلید کپی شد.")}>کپی کلید</button>
            <button className="btn" type="button" disabled={!!busy} onClick={() => void act("key", async () => {
              const value = await request<Settings>(`${API}/backup/recovery-key`, { method: "PUT", body: { key: pendingKey } });
              setSettings(value);
              setPendingKey("");
            }, "کلید بازیابی ثبت شد.")}>کلید را ذخیره کردم</button>
            <button className="btn-ghost" type="button" disabled={!!busy} onClick={() => setPendingKey("")}>انصراف</button>
          </div>
        </div>}
        <form className="org-data-import" onSubmit={upload}>
          <h3 className="font-bold">بازیابی از فایل</h3>
          {current && <div className="org-data-actions" aria-live="polite">
            <State value={current.state} />
            {current.state === "running" && <span>{current.phase === "apply" ? "در حال ثبت داده‌ها" : "در حال اعتبارسنجی فایل"}</span>}
          </div>}
          {current?.state === "succeeded" && <p className="org-data-notice" role="status">
            {fmt.int(Object.values(current.summary.counts ?? {}).reduce<number>(
              (total, count) => total + (typeof count === "number" ? 0 : count.new), 0))} رکورد وارد شد.
          </p>}
          {current?.error_code && <ErrorBox message={ERRORS[current.error_code] ?? "عملیات انجام نشد. دوباره تلاش کنید."} />}
          {!selectedBusy && !current?.can_review && <>
            <label className="org-data-file"><span><Icon icon={fileUpIcon} aria-hidden="true" /> انتخاب فایل بک‌آپ</span>
              <small><bdi>.sedasanj</bdi> · حداکثر {fileSize(settings.max_bytes)}</small>
              <span className="org-data-file-name" aria-live="polite">
                {file ? <bdi>{file.name}</bdi> : "هنوز فایلی انتخاب نشده است"}
              </span>
              <input id="org-data-file" aria-label="فایل بک‌آپ" type="file" accept=".sedasanj,application/octet-stream" required
                onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>
            {!current?.can_upload && <label><span>کلید بازیابی فایل</span>
              <input className="input" dir="ltr" type="password" autoComplete="off" required
                value={importKey} onChange={(event) => setImportKey(event.target.value)} /></label>}
            <div className="org-data-actions">
              <button className="btn-ghost" type="submit" disabled={!!busy || !file}>
                {busy === "upload" ? "در حال بارگذاری فایل…" : "بارگذاری و پیش‌نمایش"}
              </button>
              {current?.can_upload && <button className="btn-ghost" type="button" disabled={!!busy}
                onClick={() => void act("cancel", async () => {
                  await request<void>(`${API}/import/${current.id}`, { method: "DELETE" });
                  changeQuery({ archive_run: null });
                })}>لغو بارگذاری</button>}
            </div>
          </>}
        </form>
        {current?.can_review && <Review key={`${current.id}:${JSON.stringify(current.summary.owners)}`}
          run={current} members={members} busy={!!busy}
          onMap={(mappings) => void act("mapping", async () => {
            setActiveRun(await request<Run>(`${API}/import/${current.id}/mapping`, { method: "PUT", body: { mappings } }));
          })}
          onConfirm={() => setDialog("apply")}
          onCancel={() => void act("cancel", async () => {
            await request<void>(`${API}/import/${current.id}`, { method: "DELETE" });
            changeQuery({ archive_run: null });
          })} />}
        <div className="org-data-reports">
          <h3 className="font-bold">گزارش تماس</h3>
          <div className="org-data-actions">{(["csv", "json"] as const).map((format) =>
            <button className="btn-ghost" key={format} type="button" disabled={!!busy}
              onClick={() => void act("report", () => downloadFile(`/v1/account/export?format=${format}`, `calls.${format}`))}>
              خروجی <bdi>{format.toUpperCase()}</bdi>
            </button>)}</div>
        </div>
      </div>
    </Card>
    <Card title="بک‌آپ خودکار" icon={calendarClockIcon}>
      <form className="org-data-body" onSubmit={saveSettings}>
        <div className="org-data-schedule">
          <ToggleSwitch label="فعال‌سازی بک‌آپ خودکار" checked={form.enabled}
            onChange={(enabled) => setForm({ ...form, enabled })} labelClassName="font-semibold" />
          <div className="org-data-fields">
            <label><span>تکرار</span><select aria-label="تکرار" value={form.cadence}
              onChange={(event) => setForm({ ...form, cadence: event.target.value as Settings["cadence"] })}>
              <option value="daily">روزانه</option><option value="weekly">هفتگی</option>
            </select></label>
            <label><span>ساعت اجرا</span><input type="time" dir="ltr" required value={form.local_time}
              onChange={(event) => setForm({ ...form, local_time: event.target.value })} /></label>
            {form.cadence === "weekly" && <label><span>روز هفته</span><select aria-label="روز هفته" value={form.weekday}
              onChange={(event) => setForm({ ...form, weekday: Number(event.target.value) })}>
              {DAYS.map((day, index) => <option value={index} key={day}>{day}</option>)}
            </select></label>}
          </div>
          <div className="org-data-muted">منطقهٔ زمانی <bdi>{settings.timezone}</bdi>
            {settings.next_run_at && <> · اجرای بعدی <bdi>{scheduledTime(settings.next_run_at, settings.timezone)}</bdi></>}
          </div>
        </div>
        <div className="org-data-schedule">
          <h3 className="font-bold">سرور مقصد</h3>
          <div className="org-data-fields">
            <label><span>پروتکل</span><select aria-label="پروتکل" value={destination.protocol} dir="ltr"
              onChange={(event) => setDestination({ ...destination, protocol: event.target.value as Destination["protocol"] })}>
              <option value="ftps">Explicit FTPS</option>
              {(settings.allow_plain_ftp || destination.protocol === "ftp") &&
                <option value="ftp" disabled={!settings.allow_plain_ftp}>FTP</option>}
            </select></label>
            <label><span>پورت</span><input type="number" min="1" max="65535" required dir="ltr"
              value={destination.port} onChange={(event) => setDestination({ ...destination, port: Number(event.target.value) })} /></label>
            <label><span>میزبان عمومی</span><input dir="ltr" placeholder="backup.example.com" required={form.enabled}
              value={destination.host} onChange={(event) => setDestination({ ...destination, host: event.target.value })} /></label>
            <label><span>مسیر مقصد</span><input dir="ltr" required={!!destination.host}
              value={destination.directory} onChange={(event) => setDestination({ ...destination, directory: event.target.value })} /></label>
            <label><span>نام کاربری</span><input dir="ltr" autoComplete="off" required={!!destination.host}
              value={destination.username} onChange={(event) => setDestination({ ...destination, username: event.target.value })} /></label>
            <label><span>گذرواژه</span><input dir="ltr" type="password" autoComplete="new-password"
              placeholder={settings.has_password ? "ذخیره شده" : undefined} value={ftpPassword}
              onChange={(event) => setFtpPassword(event.target.value)} /></label>
          </div>
          {destination.protocol === "ftp" && <p className="org-data-caution">در FTP عادی نام کاربری و گذرواژه بدون TLS منتقل می‌شوند. فایل بک‌آپ رمزگذاری شده است.</p>}
        </div>
        <div className="org-data-actions">
          <button className="btn" type="submit" disabled={!!busy}>ذخیره تنظیمات</button>
          <button className="btn-ghost" type="button" disabled={!!busy || !destination.host || !destination.username}
            onClick={() => void act("ftp", async () => {
              await request<void>(`${API}/backup/test`, { method: "POST", body: { ...destination, password: ftpPassword || null } });
            }, "اتصال، نوشتن و تغییر نام فایل در مقصد تأیید شد.")}>
            {busy === "ftp" ? "در حال تست…" : "تست اتصال"}
          </button>
        </div>
      </form>
    </Card>
    <div className="org-data-wide">
      <Card title="تاریخچهٔ بک‌آپ و بازیابی" icon={historyIcon}>
        <div className="org-data-body">
          <div className="org-data-actions">
            <label><span>نوع عملیات</span><select aria-label="نوع عملیات" value={kind}
              onChange={(event) => changeQuery({ archive_kind: event.target.value || null, archive_offset: null })}>
              <option value="">همه</option>{Object.entries(KINDS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
            </select></label>
            <label><span>وضعیت</span><select aria-label="وضعیت" value={state}
              onChange={(event) => changeQuery({ archive_state: event.target.value || null, archive_offset: null })}>
              <option value="">همه</option><option value="active">در جریان</option>
              {(["review", "succeeded", "failed", "expired"]).map((key) => <option value={key} key={key}>{STATES[key]}</option>)}
            </select></label>
          </div>
          {history.items.length ? <ul className="org-data-history">
            {history.items.map((run) => <li key={run.id}>
              <div className="org-data-run-name">
                <strong>{KINDS[run.kind]}</strong><span>{fmt.dateTime(run.created_at)}</span>
                {run.size_bytes !== null && <span>{fileSize(run.size_bytes)}</span>}
              </div>
              <div className="org-data-run-status">
                <State value={run.state} />
                {run.transfer_state && <div className="org-data-actions"><bdi>FTP</bdi><State value={run.transfer_state} /></div>}
                {run.next_attempt_at && <small>تلاش بعدی {fmt.dateTime(run.next_attempt_at)}</small>}
                {run.error_code && <a className="org-data-help" href={`/help/errors/${run.error_code}`}>
                  {ERRORS[run.error_code] ?? "راهنمای رفع خطا"}</a>}
                {!!Object.values(run.summary.omitted ?? {}).reduce((sum, count) => sum + count, 0) &&
                  <small>{fmt.int(Object.values(run.summary.omitted ?? {}).reduce((sum, count) => sum + count, 0))} رکورد در فایل قرار نگرفت</small>}
              </div>
              <div className="org-data-actions">
                {run.can_download && <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => download(run)}>دانلود فایل</button>}
                {(run.can_review || run.can_upload) && <button
                  type="button" className="btn-ghost" onClick={() => changeQuery({ archive_run: run.id })}>ادامهٔ بازیابی</button>}
              </div>
            </li>)}
          </ul> : <p className="org-data-empty">عملیاتی برای نمایش وجود ندارد.</p>}
          <Pagination page={Math.floor(offset / limit) + 1} hasPrevious={offset > 0}
            hasNext={offset + limit < history.total && offset + limit <= 10000} total={history.total}
            onPrevious={() => changeQuery({ archive_offset: offset > limit ? String(offset - limit) : null })}
            onNext={() => changeQuery({ archive_offset: String(offset + limit) })} />
        </div>
      </Card>
    </div>
    <section className="org-data-wide org-data-danger">
      <div><h2 className="font-bold">حذف داده‌های تماس</h2><p className="org-data-muted">حذف تماس‌ها، متن‌ها، تحلیل‌ها و فایل‌های صوتی برگشت‌پذیر نیست.</p></div>
      <button className="btn-danger" type="button" disabled={!!busy} onClick={() => setDialog("delete")}>حذف کامل داده‌های تماس</button>
    </section>
    <ConfirmDialog open={dialog === "apply"} title="تأیید ورود داده‌ها" confirmLabel="ورود داده‌ها" busy={!!busy}
      description="رکوردهای جدید طبق پیش‌نمایش اضافه می‌شوند. داده‌های فعلی مقصد حفظ می‌شوند."
      onCancel={() => setDialog(null)} onConfirm={() => current && void act("apply", async () => {
        setActiveRun(await request<Run>(`${API}/import/${current.id}/confirm`, { method: "POST" }));
        setDialog(null);
      })} />
    <ConfirmDialog open={dialog === "delete"} title="حذف کامل داده‌های تماس" confirmLabel="حذف داده‌ها" busy={!!busy}
      destructive description="همه تماس‌ها، متن‌ها، تحلیل‌ها، کارهای مرتبط و فایل‌های صوتی برای همیشه حذف می‌شوند."
      onCancel={() => setDialog(null)} onConfirm={() => void act("delete", async () => {
        await request<void>(API, { method: "DELETE" });
        setDialog(null);
      }, "داده‌های تماس حذف شدند.")} />
    <ConfirmDialog open={dialog === "rotate"} title="تولید کلید جدید" confirmLabel="ساخت کلید جدید"
      description="فایل‌های قبلی همچنان با کلید زمان ساخت خود باز می‌شوند. کلید قبلی را جداگانه نگه دارید."
      onCancel={() => setDialog(null)} onConfirm={() => { setPendingKey(recoveryKey()); setDialog(null); }} />
  </div>;
}
