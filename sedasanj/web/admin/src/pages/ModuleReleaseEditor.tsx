import { lazy, Suspense, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReleaseTimeline, { SEVERITY_META } from "@cbi/web-shared/components/ReleaseTimeline";
import { fmt, request, uploadWithProgress } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import { formatBytes, sanitizeHtml } from "../sanitize";
import type { ModuleRelease, ModuleSeverity } from "../types";
import { downloadRelease } from "./ModuleReleases";

const RichTextEditor = lazy(() => import("../components/RichTextEditor"));

interface Form {
  title: string;
  changelog_html: string;
  severity: ModuleSeverity;
  channel: "stable" | "beta";
  min_freepbx_major: string;
  min_from_version: string;
}

function toForm(release: ModuleRelease): Form {
  return {
    title: release.title,
    changelog_html: release.changelog_html,
    severity: release.severity,
    channel: release.channel,
    min_freepbx_major: release.min_freepbx_major ? String(release.min_freepbx_major) : "",
    min_from_version: release.min_from_version ?? "",
  };
}

function UploadStep() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("فقط فایل zip ماژول قابل قبول است.");
      return;
    }
    setError(null);
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    try {
      const release = await uploadWithProgress<ModuleRelease>("/v1/admin/module-releases", form, setProgress);
      navigate(`/module-releases/${release.id}`, { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setProgress(null);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && progress === null) void upload(file);
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div
        className={`card flex min-h-64 cursor-pointer flex-col items-center justify-center gap-3 border-2 border-dashed text-center transition ${dragging ? "border-brand-500 bg-brand-50" : "border-slate-300"}`}
        onClick={() => progress === null && input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        {progress === null ? (
          <>
            <div className="text-lg font-bold text-slate-800">فایل zip ماژول را اینجا رها کنید</div>
            <div className="text-sm text-slate-500">
              یا کلیک کنید. نسخه از <code dir="ltr">recuploader/module.xml</code> خوانده، فایل بررسی و امضا می‌شود.
            </div>
          </>
        ) : (
          <div className="w-full max-w-md space-y-2">
            <div className="text-sm text-slate-600">
              {progress < 1 ? `در حال بارگذاری… ${fmt.digits(Math.round(progress * 100))}٪` : "در حال بررسی و امضای فایل…"}
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200">
              <div className="h-full bg-brand-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ModuleReleaseEditor() {
  const { releaseId } = useParams();
  const [release, setRelease] = useState<ModuleRelease | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!releaseId || releaseId === "new") return;
    request<ModuleRelease>(`/v1/admin/module-releases/${releaseId}`)
      .then((loaded) => {
        setRelease(loaded);
        setForm(toForm(loaded));
      })
      .catch((err) => setError(err.message));
  }, [releaseId]);

  if (!releaseId || releaseId === "new") {
    return (
      <div className="space-y-4">
        <Header />
        <UploadStep />
      </div>
    );
  }
  if (!release || !form) return error ? <ErrorBox message={error} /> : <Loading />;

  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(release));

  async function save(): Promise<ModuleRelease | null> {
    if (!release || !form) return null;
    setSaving(true);
    setError(null);
    try {
      const saved = await request<ModuleRelease>(`/v1/admin/module-releases/${release.id}`, {
        method: "PATCH",
        body: {
          title: form.title,
          changelog_html: form.changelog_html,
          severity: form.severity,
          channel: form.channel,
          min_freepbx_major: form.min_freepbx_major ? Number(fmt.latinDigits(form.min_freepbx_major)) : null,
          min_from_version: fmt.latinDigits(form.min_from_version.trim()) || null,
        },
      });
      setRelease(saved);
      setForm(toForm(saved));
      setNotice("تغییرات ذخیره شد.");
      return saved;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (!release) return;
    if (!window.confirm(`نسخهٔ ${release.version} منتشر شود؟ سرورهای FreePBX در بارگذاری بعدی صفحه آن را می‌بینند.`)) return;
    const saved = dirty ? await save() : release;
    if (!saved) return;
    setSaving(true);
    try {
      const published = await request<ModuleRelease>(`/v1/admin/module-releases/${saved.id}/publish`, { method: "POST" });
      setRelease(published);
      setForm(toForm(published));
      setNotice(`نسخهٔ ${published.version} منتشر شد.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setNotice(null);
    setForm({ ...form, [key]: value });
  };

  return (
    <div className="space-y-4">
      <Header version={release.version} status={release.status} />
      <ErrorBox message={error} />
      {notice ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{notice}</div> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="card space-y-3">
            <div>
              <label className="label">عنوان نسخه</label>
              <input className="input" value={form.title} maxLength={200} onChange={(e) => set("title", e.target.value)} />
            </div>
            <div className="flex gap-1 border-b border-slate-200">
              {(["edit", "preview"] as const).map((key) => (
                <button
                  key={key}
                  className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === key ? "border-brand-500 font-bold text-slate-900" : "border-transparent text-slate-500"}`}
                  onClick={() => setTab(key)}
                >
                  {key === "edit" ? "ویرایش تغییرات" : "پیش‌نمایش"}
                </button>
              ))}
            </div>
            {tab === "edit" ? (
              <Suspense fallback={<Loading />}>
                <RichTextEditor value={form.changelog_html} onChange={(html) => set("changelog_html", html)} />
              </Suspense>
            ) : (
              <ReleaseTimeline
                showFilters={false}
                sanitize={sanitizeHtml}
                entries={[
                  {
                    id: release.id,
                    version: release.version,
                    title: form.title,
                    severity: form.severity,
                    html: form.changelog_html,
                    published_at: release.published_at ?? new Date().toISOString(),
                  },
                ]}
              />
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card space-y-3">
            <div>
              <label className="label">اهمیت</label>
              <select className="input" value={form.severity} onChange={(e) => set("severity", e.target.value as ModuleSeverity)}>
                {(Object.keys(SEVERITY_META) as ModuleSeverity[]).map((key) => (
                  <option key={key} value={key}>{SEVERITY_META[key].label}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">نسخه‌های «امنیتی» در پنل مشتری بنر قرمز و غیرقابل‌بستن دارند.</p>
            </div>
            <div>
              <label className="label">کانال</label>
              <select className="input" value={form.channel} onChange={(e) => set("channel", e.target.value as Form["channel"])}>
                <option value="stable">پایدار (stable)</option>
                <option value="beta">آزمایشی (beta)</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">حداقل FreePBX</label>
                <input className="input" dir="ltr" inputMode="numeric" placeholder="16" value={form.min_freepbx_major} onChange={(e) => set("min_freepbx_major", e.target.value)} />
              </div>
              <div>
                <label className="label">ارتقا از نسخهٔ</label>
                <input className="input" dir="ltr" placeholder="1.3.0" value={form.min_from_version} onChange={(e) => set("min_from_version", e.target.value)} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <button className="btn-ghost" disabled={saving || !dirty} onClick={() => void save()}>ذخیره</button>
              {release.status === "draft" ? (
                <button className="btn" disabled={saving} onClick={() => void publish()}>ذخیره و انتشار</button>
              ) : null}
            </div>
          </div>

          <div className="card space-y-2 text-sm">
            <div className="font-bold text-slate-800">فایل ماژول</div>
            <Row label="نسخه"><span className="font-mono" dir="ltr">{release.version}</span></Row>
            <Row label="حجم">{formatBytes(release.artifact_size)}</Row>
            <Row label="سرورها روی این نسخه">{fmt.int(release.installations)}</Row>
            <Row label="ایجاد">{fmt.dateTime(release.created_at)}</Row>
            {release.published_at ? <Row label="انتشار">{fmt.dateTime(release.published_at)}</Row> : null}
            <div>
              <div className="text-slate-500">SHA-256</div>
              <code className="block break-all rounded bg-slate-50 p-2 text-xs" dir="ltr">{release.artifact_sha256}</code>
            </div>
            <button className="btn-ghost w-full text-sm" onClick={() => downloadRelease(release).catch((err) => setError(err.message))}>دانلود zip</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800">{children}</span>
    </div>
  );
}

function Header({ version, status }: { version?: string; status?: ModuleRelease["status"] }) {
  const labels = { draft: "پیش‌نویس", published: "منتشرشده", revoked: "لغوشده" };
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <Link to="/module-releases" className="text-sm text-slate-500 hover:text-slate-800">← نسخه‌های ماژول</Link>
        <h1 className="text-xl font-extrabold text-slate-900">
          {version ? <>نسخهٔ <span dir="ltr">v{version}</span></> : "ثبت نسخهٔ جدید"}
          {status ? <span className="badge mr-2 bg-slate-100 align-middle text-slate-600">{labels[status]}</span> : null}
        </h1>
      </div>
    </div>
  );
}
