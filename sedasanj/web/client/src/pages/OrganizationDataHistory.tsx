import historyIcon from "@iconify-icons/lucide/history";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, query, request } from "../api";
import { PageHeader } from "../components/PageHeader";
import { ErrorBox, Pagination } from "../components/Widgets";
import { useTablePageSize } from "../lib/useTablePagination";
import { API, Card, ERRORS, fileSize, KINDS, ORGANIZATION_DATA_PATH, State, STATES, type Run } from "./organizationDataShared";

const FILTER_STATES = ["active", "review", "succeeded", "failed", "expired"] as const;

export default function OrganizationDataHistory() {
  const [params, setParams] = useSearchParams();
  const [limit] = useTablePageSize();
  const [history, setHistory] = useState<{ items: Run[]; total: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const requestedKind = params.get("archive_kind") ?? "";
  const requestedState = params.get("archive_state") ?? "";
  const kind = Object.hasOwn(KINDS, requestedKind) ? requestedKind : "";
  const state = FILTER_STATES.find((value) => value === requestedState) ?? "";
  const rawOffset = Number(params.get("archive_offset"));
  const offset = Number.isInteger(rawOffset) && rawOffset > 0 && rawOffset <= 10000 ? rawOffset : 0;

  function changeQuery(values: Record<string, string | null>) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
      return next;
    }, { replace: true });
  }

  useEffect(() => {
    let stopped = false;
    let pending = false;
    setHistory(null);
    setLoadError(null);
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const page = await request<{ items: Run[]; total: number }>(`${API}/runs${query({
          limit, offset, kind, state,
        })}`);
        if (!stopped) {
          setHistory(page);
          setLoadError(null);
        }
      } catch (cause) {
        if (!stopped) setLoadError((cause as Error).message);
      } finally { pending = false; }
    }
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [kind, state, limit, offset]);

  async function download(run: Run) {
    setDownloading(true);
    setDownloadError(null);
    try {
      const url = `${API}/runs/${run.id}/download`;
      await request<void>(url, { method: "POST" });
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (cause) {
      setDownloadError((cause as Error).message);
    } finally {
      setDownloading(false);
    }
  }

  return <div className="org-data-controls space-y-4" dir="rtl">
    <PageHeader title="تاریخچهٔ بک‌آپ و بازیابی"
      actions={<Link className="btn-ghost" to={ORGANIZATION_DATA_PATH}>بازگشت به داده‌های سازمان</Link>} />
    <Card title="عملیات بک‌آپ و بازیابی" icon={historyIcon}>
      <div className="org-data-body">
        <div className="org-data-actions">
          <label><span>نوع عملیات</span><select aria-label="نوع عملیات" value={kind}
            onChange={(event) => changeQuery({ archive_kind: event.target.value || null, archive_offset: null })}>
            <option value="">همه</option>{Object.entries(KINDS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
          </select></label>
          <label><span>وضعیت</span><select aria-label="وضعیت" value={state}
            onChange={(event) => changeQuery({ archive_state: event.target.value || null, archive_offset: null })}>
            <option value="">همه</option>
            {FILTER_STATES.map((key) => <option value={key} key={key}>{key === "active" ? "در جریان" : STATES[key]}</option>)}
          </select></label>
        </div>
        <ErrorBox message={loadError ?? downloadError} />
        {history ? <>
          {history.items.length ? <ul className="org-data-history">
            {history.items.map((run) => {
              const omitted = Object.values(run.summary.omitted ?? {}).reduce((sum, count) => sum + count, 0);
              return <li key={run.id}>
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
                  {omitted > 0 && <small>{fmt.int(omitted)} رکورد در فایل قرار نگرفت</small>}
                </div>
                <div className="org-data-actions">
                  {run.can_download && <button type="button" className="btn-ghost" disabled={downloading}
                    onClick={() => void download(run)}>دانلود فایل</button>}
                  {(run.can_review || run.can_upload) && <Link className="btn-ghost"
                    to={`${ORGANIZATION_DATA_PATH}&archive_run=${encodeURIComponent(run.id)}`}>ادامهٔ بازیابی</Link>}
                </div>
              </li>;
            })}
          </ul> : <p className="org-data-empty">عملیاتی برای نمایش وجود ندارد.</p>}
          <Pagination page={Math.floor(offset / limit) + 1} hasPrevious={offset > 0}
            hasNext={offset + limit < history.total && offset + limit <= 10000} total={history.total}
            onPrevious={() => changeQuery({ archive_offset: offset > limit ? String(offset - limit) : null })}
            onNext={() => changeQuery({ archive_offset: String(offset + limit) })} />
        </> : !loadError && <div className="org-data-history" role="status" aria-label="در حال بارگذاری تاریخچه">
          <span className="org-data-skeleton !h-12 w-full" />
          <span className="org-data-skeleton !h-12 w-full" />
          <span className="org-data-skeleton w-36" />
        </div>}
      </div>
    </Card>
  </div>;
}
