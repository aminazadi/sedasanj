import { useState } from "react";
import { fmt, formatJobError, request } from "../api";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import type { Job, Page } from "../types";
import FilterBar, { FilterSelect } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

type Operations = {job_counts:Record<string,number>;outbox_total:number;outbox_pending:Array<{id:string;queue_name:string;function_name:string;attempts:number;wait_seconds:number;last_error:string|null}>};

const COLUMNS: SkeletonColumn[] = [
  { label: "نوع", width: "3rem" },
  { label: "تماس", width: "10rem", dir: "ltr", cellClassName: "max-w-[16rem] truncate" },
  { label: "تلاش", width: "1.5rem" },
  { label: "اجرا پس از", width: "8.5rem" },
  { label: "خطا", width: "12rem", cellClassName: "max-w-md whitespace-normal" },
  { label: null, width: "5.5rem", height: "1.875rem" },
];

const KINDS = ["", "asr", "emotion", "llm", "notify"];
const DEFAULT_STATUS = "failed_retryable";

export default function Jobs() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [outboxOffset, setOutboxOffset] = useState(0);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState(DEFAULT_STATUS);
  const [error, setError] = useState<string | null>(null);
  const jobsData = useResource<{ page: Page<Job>; operations: Operations }>(async (signal) => {
    const params = new URLSearchParams({ status, limit: String(limit), offset: String(offset) });
    if (kind) params.set("kind", kind);
    const [page, operations] = await Promise.all([
      request<Page<Job>>(`/v1/admin/jobs?${params.toString()}`, { signal }),
      request<Operations>(`/v1/admin/operations?offset=${outboxOffset}&limit=${limit}`, { signal }),
    ]);
    return { page, operations };
  }, [kind, offset, outboxOffset, status]);
  const reload = async () => jobsData.reload();
  const page = jobsData.data?.page ?? null;
  const operations = jobsData.data?.operations ?? null;
  const jobs = page?.items ?? null;

  async function requeue(jobId: string) {
    try {
      await request(`/v1/admin/jobs/${jobId}/requeue`, { method: "POST" });
      jobsData.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={jobsData.error ?? error} />
      <FilterBar
        hasActive={Boolean(kind) || status !== DEFAULT_STATUS}
        onClear={() => { setKind(""); setStatus(DEFAULT_STATUS); setOffset(0); }}
        actions={<button type="button" className="btn min-h-[42px]" onClick={() => void reload()}>بازخوانی</button>}
        fields={[
          { id: "status", label: "وضعیت", pinned: true, active: status !== DEFAULT_STATUS, onRemove: () => { setStatus(DEFAULT_STATUS); setOffset(0); }, control: <FilterSelect allLabel={null} value={status} onChange={(value) => { setStatus(value); setOffset(0); }} options={[{ value: "failed_retryable", label: "خطای موقت" }, { value: "failed_terminal", label: "خطای نهایی" }, { value: "queued", label: "در صف" }, { value: "running", label: "در اجرا" }, { value: "succeeded", label: "موفق" }]} /> },
          { id: "kind", label: "نوع کار", active: Boolean(kind), onRemove: () => { setKind(""); setOffset(0); }, control: <FilterSelect value={kind} onChange={(value) => { setKind(value); setOffset(0); }} options={KINDS.filter(Boolean).map((item) => ({ value: item, label: item }))} /> },
        ]}
      />

      <div className="card">
        {jobsData.loading ? (
          <SkeletonTable columns={COLUMNS} rows={jobs?.length ? Math.min(jobs.length, limit) : 8} />
        ) : !jobs || jobs.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>نوع</th>
                <th>تماس</th>
                <th>تلاش</th>
                <th>اجرا پس از</th>
                <th>خطا</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.kind}</td>
                  <td dir="ltr" className="max-w-[16rem] truncate">
                    {fmt.digits(job.call_id)}
                  </td>
                  <td>{fmt.int(job.attempt)}</td>
                  <td>{fmt.dateTime(job.run_after)}</td>
                  <td
                    className="max-w-md whitespace-normal text-rose-700"
                    title={job.error_detail ?? undefined}
                  >
                    {formatJobError(job.error_code, job.error_detail)}
                  </td>
                  <td>
                    <button className="btn-ghost text-xs" onClick={() => void requeue(job.id)}>
                      اجرای مجدد
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      {operations ? <div className="card overflow-x-auto"><h2 className="mb-3 font-bold">Outbox پایدار</h2>{operations.outbox_pending.length===0?<Empty/>:<table className="table"><thead><tr><th>صف</th><th>تابع</th><th>تلاش</th><th>انتظار</th><th>آخرین خطا</th></tr></thead><tbody>{operations.outbox_pending.map(item=><tr key={item.id}><td>{item.queue_name}</td><td dir="ltr">{item.function_name}</td><td>{fmt.int(item.attempts)}</td><td>{fmt.int(item.wait_seconds)} ثانیه</td><td className="max-w-md whitespace-normal text-xs text-rose-700">{item.last_error??'—'}</td></tr>)}</tbody></table>}<Pagination offset={outboxOffset} limit={limit} total={operations.outbox_total} onChange={setOutboxOffset}/></div>:null}
    </div>
  );
}
