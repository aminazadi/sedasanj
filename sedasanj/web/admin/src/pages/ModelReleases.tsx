import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, fmt, request, tokens } from "../api";
import { useSensitiveAction } from "../components/SensitiveActionDialog";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import { modelErrorMessage } from "../lib/mlModelErrors";
import { formatBytes } from "../sanitize";
import type { MlModelChannel, MlModelRelease, MlModelReleasePage, MlModelStatus } from "../types";

export const STATUS_META: Record<MlModelStatus, { label: string; className: string }> = {
  uploading: { label: "در حال آپلود", className: "bg-amber-50 text-amber-700" },
  ready: { label: "آماده", className: "bg-emerald-50 text-emerald-700" },
  revoked: { label: "باطل‌شده", className: "bg-rose-50 text-rose-700" },
  deleted: { label: "فایل حذف‌شده", className: "bg-slate-100 text-slate-500" },
};

const CHANNEL_LABEL: Record<MlModelChannel, string> = { latest: "آخرین (latest)", champion: "برگزیده (champion)" };

const FILTERS: Array<{ value: MlModelStatus | ""; label: string }> = [
  { value: "", label: "همه" },
  { value: "ready", label: "آماده" },
  { value: "revoked", label: "باطل‌شده" },
  { value: "deleted", label: "حذف‌شده" },
];

export async function downloadModel(model: MlModelRelease): Promise<void> {
  const response = await fetch(`/v1/admin/ml/models/${model.id}/download`, {
    headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
  });
  if (!response.ok) {
    throw new ApiError(response.status, "download", "دانلود مدل ناموفق بود. فهرست را تازه کنید و دوباره تلاش کنید.");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `${model.kind}-${model.version}.onnx`;
  link.click();
  URL.revokeObjectURL(url);
}

function metricsSummary(metrics: Record<string, unknown>): string {
  const parts = Object.entries(metrics)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .slice(0, 4)
    .map(([name, value]) => `${name}=${typeof value === "number" ? Number(value.toPrecision(4)) : value}`);
  return parts.length ? parts.join("  ") : "—";
}

function CopyHash({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="font-mono text-xs text-slate-600 hover:text-brand-600"
      dir="ltr"
      title="کپی SHA-256"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "کپی شد ✓" : `${value.slice(0, 12)}…`}
    </button>
  );
}

export default function ModelReleases() {
  const [params, setParams] = useSearchParams();
  const rawFilter = params.get("status") ?? "";
  const filter = (rawFilter in STATUS_META ? rawFilter : "") as MlModelStatus | "";
  const setFilter = (value: string) =>
    setParams((old) => {
      const next = new URLSearchParams(old);
      if (value) next.set("status", value); else next.delete("status");
      return next;
    });
  const [page, setPage] = useState<MlModelReleasePage | null>(null);
  const [latest, setLatest] = useState<MlModelRelease[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [askProof, proofDialog] = useSensitiveAction();

  const reload = useCallback(async () => {
    try {
      const query = new URLSearchParams({ limit: "200" });
      if (filter) query.set("status", filter);
      const [all, current] = await Promise.all([
        request<MlModelReleasePage>(`/v1/admin/ml/models?${query}`),
        request<MlModelReleasePage>("/v1/admin/ml/models?channel=latest&status=ready&limit=50"),
      ]);
      setPage(all);
      setLatest(current.items);
      setError(null);
    } catch (err) {
      setError(modelErrorMessage(err));
    }
  }, [filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const byKind = useMemo(() => {
    const groups = new Map<string, MlModelRelease[]>();
    for (const item of page?.items ?? []) groups.set(item.kind, [...(groups.get(item.kind) ?? []), item]);
    return [...groups.entries()];
  }, [page]);

  async function act(model: MlModelRelease, action: "promote" | "rollout" | "pin" | "revoke" | "delete") {
    const label = `${model.kind} ${model.version}`;
    const prompts = {
      promote: `مدل ${label} به «برگزیده» ارتقا یابد؟ نسخهٔ برگزیدهٔ قبلی پس از ${page?.prev_retention_hours ?? 72} ساعت حذف می‌شود، مگر پین شده باشد.`,
      rollout: `درصد انتشار مدل ${label} تغییر کند؟`,
      pin: model.pinned
        ? `پین مدل ${label} برداشته شود؟ پس از پایان مهلت نگهداری فایل حذف می‌شود.`
        : `مدل ${label} پین شود تا فایل آن خودکار حذف نشود؟`,
      revoke: `مدل ${label} باطل شود؟ فایل آن همین حالا از ذخیره‌سازی پاک می‌شود و برگشت‌پذیر نیست.`,
      delete: `ردیف مدل ${label} برای همیشه حذف شود؟`,
    };
    let extra: Record<string, unknown> = {};
    if (action === "rollout") {
      const answer = window.prompt("درصد انتشار (۰ تا ۱۰۰):", String(model.rollout_percent));
      if (answer === null) return;
      const percent = Number(fmt.latinDigits(answer));
      if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
        setError("درصد انتشار باید عدد صحیح بین ۰ تا ۱۰۰ باشد.");
        return;
      }
      extra = { rollout_percent: percent };
    }
    if (action === "pin") extra = { pinned: !model.pinned };
    const proof = await askProof(prompts[action]);
    if (!proof) return;
    setBusy(model.id);
    try {
      await request(`/v1/admin/ml/models/${model.id}/${action}`, { method: "POST", body: { ...proof, ...extra } });
      await reload();
    } catch (err) {
      setError(modelErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {proofDialog}
      <ErrorBox message={error} />

      <div className="card">
        <div className="mb-3 text-sm font-bold text-slate-700">آخرین مدل در حال آموزش</div>
        {!page ? (
          <Loading />
        ) : latest.length === 0 ? (
          <Empty>هنوز مدلی از سرور آموزش منتشر نشده است.</Empty>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {latest.map((model) => (
              <div key={model.id} className="rounded-xl border border-slate-200 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-mono font-bold" dir="ltr">{model.kind}</div>
                  <span className="badge bg-brand-50 text-brand-700" dir="ltr">v{model.version}</span>
                </div>
                <div className="mt-2 text-xs text-slate-500">
                  آخرین به‌روزرسانی: {model.ready_at ? fmt.dateTime(model.ready_at) : "—"} · حجم: {formatBytes(model.size_bytes)}
                </div>
                <div className="mt-2 font-mono text-xs text-slate-600" dir="ltr">{metricsSummary(model.metrics)}</div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <CopyHash value={model.sha256} />
                  <button className="btn text-sm" onClick={() => downloadModel(model).catch((err) => setError(modelErrorMessage(err)))}>
                    دانلود مدل
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          کانال latest همیشه فقط یک نسخه نگه می‌دارد و با آماده‌شدن نسخهٔ تازه، فایل قبلی حذف می‌شود. پس از دانلود، SHA-256 فایل را با مقدار نمایش‌داده‌شده مقایسه کنید.
        </p>
      </div>

      <div className="card">
        <div className="mb-4 flex flex-wrap gap-1">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              className={`rounded-lg px-3 py-1.5 text-sm ${filter === item.value ? "bg-brand-500 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              onClick={() => setFilter(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {!page ? (
          <Loading />
        ) : byKind.length === 0 ? (
          <Empty>مدلی ثبت نشده است.</Empty>
        ) : (
          byKind.map(([kind, models]) => (
            <div key={kind} className="mb-6 last:mb-0">
              <h3 className="mb-2 font-mono text-sm font-bold text-slate-800" dir="ltr">{kind}</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>نسخه</th>
                      <th>کانال</th>
                      <th>وضعیت</th>
                      <th>معیارها</th>
                      <th>SHA-256</th>
                      <th>انتشار</th>
                      <th>تاریخ</th>
                      <th>حجم</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((model) => (
                      <tr key={model.id}>
                        <td className="font-mono font-bold" dir="ltr">v{model.version}</td>
                        <td>
                          {CHANNEL_LABEL[model.channel]}
                          {model.pinned ? <span className="badge mr-1 bg-sky-50 text-sky-700">پین</span> : null}
                          {model.superseded_at && model.status === "ready" ? (
                            <div className="text-xs text-slate-400">جایگزین‌شده؛ در انتظار حذف</div>
                          ) : null}
                        </td>
                        <td><span className={`badge ${STATUS_META[model.status].className}`}>{STATUS_META[model.status].label}</span></td>
                        <td className="max-w-[14rem] truncate font-mono text-xs" dir="ltr" title={JSON.stringify(model.metrics)}>
                          {metricsSummary(model.metrics)}
                        </td>
                        <td><CopyHash value={model.sha256} /></td>
                        <td className="font-mono" dir="ltr">{model.rollout_percent}%</td>
                        <td>{fmt.dateTime(model.ready_at ?? model.created_at)}</td>
                        <td>{formatBytes(model.size_bytes)}</td>
                        <td className="whitespace-nowrap">
                          {model.status === "ready" ? (
                            <>
                              <button className="btn-ghost text-xs" onClick={() => downloadModel(model).catch((err) => setError(modelErrorMessage(err)))}>دانلود</button>{" "}
                              {model.channel === "latest" ? (
                                <button className="btn-ghost text-xs" disabled={busy === model.id} onClick={() => act(model, "promote")}>ارتقا</button>
                              ) : null}{" "}
                              <button className="btn-ghost text-xs" disabled={busy === model.id} onClick={() => act(model, "rollout")}>درصد انتشار</button>{" "}
                              <button className="btn-ghost text-xs" disabled={busy === model.id} onClick={() => act(model, "pin")}>{model.pinned ? "برداشتن پین" : "پین"}</button>{" "}
                              <button className="btn-ghost text-xs text-rose-700" disabled={busy === model.id} onClick={() => act(model, "revoke")}>ابطال</button>
                            </>
                          ) : (
                            <button className="btn-ghost text-xs text-rose-700" disabled={busy === model.id} onClick={() => act(model, "delete")}>حذف ردیف</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
