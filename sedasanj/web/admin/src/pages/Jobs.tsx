import { useCallback, useEffect, useState } from "react";
import { fmt, formatJobError, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Job, Page } from "../types";
import TableFilters from "@cbi/web-shared/components/TableFilters";

const KINDS = ["", "asr", "emotion", "llm", "notify"];

export default function Jobs() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [outboxOffset, setOutboxOffset] = useState(0);
  const [page, setPage] = useState<Page<Job> | null>(null);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("failed_retryable");
  const [error, setError] = useState<string | null>(null);
  const [operations, setOperations] = useState<{job_counts:Record<string,number>;outbox_total:number;outbox_pending:Array<{id:string;queue_name:string;function_name:string;attempts:number;wait_seconds:number;last_error:string|null}>}|null>(null);

  const reload = useCallback(async () => {
    try {
      const params = new URLSearchParams({ status, limit: String(limit), offset: String(offset) });
      if (kind) params.set("kind", kind);
      setPage(await request<Page<Job>>(`/v1/admin/jobs?${params.toString()}`));
      setOperations(await request<{job_counts:Record<string,number>;outbox_total:number;outbox_pending:Array<{id:string;queue_name:string;function_name:string;attempts:number;wait_seconds:number;last_error:string|null}>}>(`/v1/admin/operations?offset=${outboxOffset}&limit=${limit}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [kind, offset, outboxOffset, status]);
  const jobs = page?.items ?? null;

  useEffect(() => {
    void reload();
  }, [reload]);

  async function requeue(jobId: string) {
    try {
      await request(`/v1/admin/jobs/${jobId}/requeue`, { method: "POST" });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <TableFilters><div className="flex flex-wrap gap-3">
        <div>
          <label className="label">نوع کار</label>
          <select className="input" value={kind} onChange={(event) => { setKind(event.target.value); setOffset(0); }}>
            {KINDS.map((item) => (
              <option key={item} value={item}>
                {item || "همه"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">وضعیت</label>
          <select
            className="input"
            value={status}
            onChange={(event) => { setStatus(event.target.value); setOffset(0); }}
          >
            <option value="failed_retryable">خطای موقت</option>
            <option value="failed_terminal">خطای نهایی</option>
            <option value="queued">در صف</option>
            <option value="running">در اجرا</option>
            <option value="succeeded">موفق</option>
          </select>
        </div>
        <div className="flex items-end">
          <button className="btn" onClick={() => void reload()}>
            بازخوانی
          </button>
        </div>
      </div></TableFilters>

      <div className="card">
        {!jobs ? (
          <Loading />
        ) : jobs.length === 0 ? (
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
