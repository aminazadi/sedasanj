import { lazy, Suspense, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import ReleaseTimeline from "@cbi/web-shared/components/ReleaseTimeline";
import { fmt, request, uploadWithProgress } from "../api";
import { useSensitiveAction } from "../components/SensitiveActionDialog";
import { ErrorBox, Loading } from "../components/Widgets";
import { releaseErrorMessage } from "../lib/jalaseNegarErrors";
import { formatBytes, sanitizeHtml } from "../sanitize";
import type { JalaseNegarRelease, JalaseNegarReleaseChannel } from "../types";
import { downloadApk, STATUS_META } from "./JalaseNegarReleases";

const RichTextEditor = lazy(() => import("../components/RichTextEditor"));
const MAX_APK_BYTES = 200 * 1024 * 1024;

function UploadStep() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    if (!/\.apk$/i.test(file.name)) {
      setError("فایل APK جلسه‌نگار را انتخاب کنید (پسوند .apk).");
      return;
    }
    if (file.size > MAX_APK_BYTES) {
      setError("حجم APK از ۲۰۰ مگابایت بیشتر است. حجم برنامه را کم کنید و دوباره انتخاب کنید.");
      return;
    }
    setError(null);
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    try {
      const release = await uploadWithProgress<JalaseNegarRelease>("/v1/admin/jalase-negar/releases", form, setProgress);
      navigate(`/jalase-negar-releases/${release.id}`, { replace: true });
    } catch (err) {
      setError(releaseErrorMessage(err));
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
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          type="file"
          accept=".apk,application/vnd.android.package-archive"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        {progress === null ? (
          <>
            <div className="text-lg font-bold text-slate-800">APK جلسه‌نگار را اینجا رها کنید</div>
            <div className="text-sm text-slate-500">
              یا کلیک کنید. نسخه، شماره ساخت، حداقل اندروید، معماری و امضای فایل خوانده و بررسی می‌شود؛ فقط APK رسمی release پذیرفته می‌شود.
            </div>
          </>
        ) : (
          <div className="w-full max-w-md space-y-2">
            <div className="text-sm text-slate-600">
              {progress < 1 ? `در حال بارگذاری… ${fmt.digits(Math.round(progress * 100))}٪` : "در حال بررسی امضا و ذخیره فایل…"}
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

export default function JalaseNegarReleaseEditor() {
  const { releaseId } = useParams();
  const [release, setRelease] = useState<JalaseNegarRelease | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [rollout, setRollout] = useState(100);
  const [minSupported, setMinSupported] = useState(0);
  const [channel, setChannel] = useState<JalaseNegarReleaseChannel>("stable");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "preview" ? "preview" : "edit";
  const setTab = (value: "edit" | "preview") => setParams((old) => { const next = new URLSearchParams(old); next.set("tab", value); return next; });
  const [saving, setSaving] = useState(false);
  const [askProof, proofDialog] = useSensitiveAction();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function adopt(loaded: JalaseNegarRelease) {
    setRelease(loaded);
    setTitle(loaded.title);
    setNotes(loaded.changelog_html);
    setRollout(loaded.rollout_percent);
    setMinSupported(loaded.min_supported_version_code);
    setChannel(loaded.channel);
  }

  useEffect(() => {
    if (!releaseId || releaseId === "new") return;
    request<JalaseNegarRelease>(`/v1/admin/jalase-negar/releases/${releaseId}`)
      .then(adopt)
      .catch((err) => setError(releaseErrorMessage(err)));
  }, [releaseId]);

  if (!releaseId || releaseId === "new") {
    return (
      <div className="space-y-4">
        <Header />
        <UploadStep />
      </div>
    );
  }
  if (!release) return error ? <ErrorBox message={error} /> : <Loading />;

  const dirty =
    title !== release.title ||
    notes !== release.changelog_html ||
    rollout !== release.rollout_percent ||
    minSupported !== release.min_supported_version_code ||
    channel !== release.channel;

  async function save(): Promise<JalaseNegarRelease | null> {
    if (!release) return null;
    setSaving(true);
    setError(null);
    try {
      const saved = await request<JalaseNegarRelease>(`/v1/admin/jalase-negar/releases/${release.id}`, {
        method: "PATCH",
        body: { title, changelog_html: notes, rollout_percent: rollout, min_supported_version_code: minSupported, channel },
      });
      adopt(saved);
      setNotice("تغییرات ذخیره شد.");
      return saved;
    } catch (err) {
      setError(releaseErrorMessage(err));
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function transition(action: "publish" | "revoke") {
    if (!release) return;
    const proof = await askProof(
      action === "publish"
        ? `نسخهٔ ${release.version_name} منتشر شود؟ اپ‌های نصب‌شده در اجرای بعدی آن را پیشنهاد می‌دهند.`
        : `انتشار نسخهٔ ${release.version_name} لغو شود؟ پیشنهاد و دانلود آن فوراً متوقف می‌شود.`,
    );
    if (!proof) return;
    const saved = action === "publish" && dirty ? await save() : release;
    if (!saved) return;
    setSaving(true);
    try {
      const updated = await request<JalaseNegarRelease>(`/v1/admin/jalase-negar/releases/${saved.id}/${action}`, { method: "POST", body: proof });
      adopt(updated);
      setNotice(action === "publish" ? `نسخهٔ ${updated.version_name} منتشر شد.` : `انتشار نسخهٔ ${updated.version_name} لغو شد.`);
    } catch (err) {
      setError(releaseErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!release || !window.confirm(`پیش‌نویس ${release.version_name} و فایل آن برای همیشه حذف شود؟`)) return;
    setSaving(true);
    try {
      await request(`/v1/admin/jalase-negar/releases/${release.id}`, { method: "DELETE" });
      navigate("/jalase-negar-releases", { replace: true });
    } catch (err) {
      setError(releaseErrorMessage(err));
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      {proofDialog}
      <Header version={release.version_name} status={release.status} />
      <ErrorBox message={error} />
      {notice ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{notice}</div> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="card space-y-3">
            <div>
              <label className="label">عنوان نسخه</label>
              <input className="input" value={title} maxLength={200} onChange={(e) => { setNotice(null); setTitle(e.target.value); }} />
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
                <RichTextEditor value={notes} onChange={(html) => { setNotice(null); setNotes(html); }} />
              </Suspense>
            ) : (
              <div className="space-y-4">
                <ReleaseTimeline
                  showFilters={false}
                  sanitize={sanitizeHtml}
                  entries={[{ id: release.id, version: release.version_name, title, severity: "normal", html: notes, published_at: release.published_at ?? new Date().toISOString() }]}
                />
                <div>
                  <div className="mb-1 text-sm font-bold text-slate-700">نمای داخل اپ (متن ساده)</div>
                  <pre className="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm" dir="auto">
                    {plainPreview(notes) || "—"}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card flex flex-wrap gap-2">
            <button className="btn-ghost" disabled={saving || !dirty} onClick={() => void save()}>ذخیره</button>
            {release.status === "draft" ? (
              <>
                <button className="btn" disabled={saving} onClick={() => void transition("publish")}>ذخیره و انتشار</button>
                <button className="btn-ghost text-rose-700" disabled={saving} onClick={() => void remove()}>حذف پیش‌نویس</button>
              </>
            ) : null}
            {release.status === "published" ? (
              <button className="btn-ghost text-rose-700" disabled={saving} onClick={() => void transition("revoke")}>لغو انتشار</button>
            ) : null}
          </div>
          <div className="card space-y-3 text-sm">
            <div className="font-bold text-slate-800">انتشار مرحله‌ای به‌روزرسانی خودکار</div>
            <div>
              <label className="label">درصد انتشار (۰ تا ۱۰۰)</label>
              <input
                className="input" type="number" min={0} max={100} dir="ltr" value={rollout}
                onChange={(e) => { setNotice(null); setRollout(Math.min(100, Math.max(0, Math.round(Number(e.target.value) || 0)))); }}
              />
              <div className="mt-1 text-xs text-slate-500">هر نصب با شناسهٔ تصادفی خودش در یک گروه ثابت قرار دارد؛ با افزایش درصد، گروه‌های بیشتری پیشنهاد را می‌گیرند. ۰ یعنی فعلاً به هیچ نصبی پیشنهاد نمی‌شود.</div>
            </div>
            <div>
              <label className="label">حداقل شماره ساخت پشتیبانی‌شده</label>
              <input
                className="input" type="number" min={0} max={release.version_code} dir="ltr" value={minSupported}
                onChange={(e) => { setNotice(null); setMinSupported(Math.max(0, Math.round(Number(e.target.value) || 0))); }}
              />
              <div className="mt-1 text-xs text-slate-500">نصب‌هایی با شماره ساخت کمتر از این عدد، بدون توجه به درصد انتشار، به‌روزرسانی را اجباری می‌بینند. فقط برای ناسازگاری پروتکل استفاده کنید؛ ۰ یعنی غیرفعال.</div>
            </div>
            <div>
              <label className="label">کانال</label>
              <select className="input" value={channel} onChange={(e) => { setNotice(null); setChannel(e.target.value as JalaseNegarReleaseChannel); }}>
                <option value="stable">پایدار (همه)</option>
                <option value="beta">آزمایشی (فقط نصب‌های آزمایشی)</option>
              </select>
            </div>
          </div>
          <div className="card space-y-2 text-sm">
            <div className="font-bold text-slate-800">مشخصات فایل (خوانده‌شده از APK)</div>
            <Row label="شناسه بسته"><span className="font-mono text-xs" dir="ltr">{release.package_name}</span></Row>
            <Row label="نسخه"><span className="font-mono" dir="ltr">{release.version_name}</span></Row>
            <Row label="شماره ساخت"><span className="font-mono" dir="ltr">{release.version_code}</span></Row>
            <Row label="حداقل اندروید"><span dir="ltr">API {release.min_sdk}</span></Row>
            <Row label="معماری‌ها"><span className="font-mono text-xs" dir="ltr">{release.abis.join(", ") || "همه"}</span></Row>
            <Row label="حجم">{formatBytes(release.artifact_size)}</Row>
            <Row label="ایجاد">{fmt.dateTime(release.created_at)}</Row>
            {release.published_at ? <Row label="انتشار">{fmt.dateTime(release.published_at)}</Row> : null}
            {release.revoked_at ? <Row label="لغو">{fmt.dateTime(release.revoked_at)}</Row> : null}
            <Hash label="SHA-256 فایل" value={release.artifact_sha256} />
            <Hash label="SHA-256 گواهی امضا" value={release.signing_cert_sha256} />
            <button className="btn-ghost w-full text-sm" onClick={() => downloadApk(release).catch((err) => setError(releaseErrorMessage(err)))}>دانلود APK</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function plainPreview(html: string): string {
  const doc = new DOMParser().parseFromString(sanitizeHtml(html).replace(/<\/(p|li|h\d|div)>|<br\s*\/?>/gi, "\n"), "text/html");
  return (doc.body.textContent ?? "").replace(/\n{3,}/g, "\n\n").trim();
}

function Hash({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <code className="block break-all rounded bg-slate-50 p-2 text-xs" dir="ltr">{value}</code>
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

function Header({ version, status }: { version?: string; status?: JalaseNegarRelease["status"] }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <Link to="/jalase-negar-releases" className="text-sm text-slate-500 hover:text-slate-800">→ نسخه‌های جلسه‌نگار</Link>
        <h1 className="text-xl font-extrabold text-slate-900">
          {version ? <>نسخهٔ <span dir="ltr">v{version}</span></> : "ثبت نسخهٔ جدید"}
          {status ? <span className={`badge mr-2 align-middle ${STATUS_META[status].className}`}>{STATUS_META[status].label}</span> : null}
        </h1>
      </div>
    </div>
  );
}
