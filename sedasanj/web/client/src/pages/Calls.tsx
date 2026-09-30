import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fmt, INTENT_LABELS, query, request, SENTIMENT_LABELS } from "../api";
import { isOperator, isOrgAdmin, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination, SentimentBadge, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import type { CallPage, CallSummary } from "../types";
import CallUploadForm from "./CallUploadForm";

interface Filters {
  from: string;
  to: string;
  q: string;
  intent: string;
  sentiment: string;
  number: string;
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-4 w-4">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  );
}

const EMPTY: Filters = { from: "", to: "", q: "", intent: "", sentiment: "", number: "" };

export default function Calls() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const canDelete = isOrgAdmin(session?.role);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [items, setItems] = useState<CallSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paginated, setPaginated] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const hasAppliedFilters = Object.values(applied).some(Boolean);
  const appliedFiltersUnchanged =
    hasAppliedFilters &&
    (Object.keys(applied) as Array<keyof Filters>).every((key) => applied[key] === filters[key]);

  const load = useCallback(
    async (next: Filters, after: string | null, silent = false) => {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const page = await request<CallPage>(
          `/v1/calls${query({ ...next, cursor: after, limit: 50 })}`,
        );
        setItems(page.items);
        setCursor(page.next_cursor);
        setTotal(page.total);
        setPaginated(Boolean(after));
      } catch (err) {
        if (!silent) setError((err as Error).message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    setCursorHistory([null]);
    setPageIndex(0);
    void load(applied, null);
  }, [applied, load]);

  useEffect(() => {
    if (paginated || !items.some((call) => call.processing)) return;
    const timer = window.setInterval(() => {
      void load(applied, null, true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [applied, items, load, paginated]);

  async function deleteCall(call: CallSummary) {
    if (!window.confirm("این تماس، فایل صوتی، متن، تحلیل‌ها و کارهای مرتبط برای همیشه حذف می‌شوند. ادامه می‌دهید؟")) return;
    setDeletingId(call.id);
    setError(null);
    try {
      await request<void>(`/v1/calls/${call.id}`, { method: "DELETE" });
      setItems((current) => current.filter((item) => item.id !== call.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  function nextPage() {
    if (!cursor) return;
    const nextIndex = pageIndex + 1;
    setCursorHistory((current) => [...current.slice(0, nextIndex), cursor]);
    setPageIndex(nextIndex);
    void load(applied, cursor);
  }

  function previousPage() {
    if (pageIndex === 0) return;
    const previousIndex = pageIndex - 1;
    setPageIndex(previousIndex);
    void load(applied, cursorHistory[previousIndex]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold">تماس‌ها</h1>
          {operator ? (
            <p className="mt-1 text-xs text-slate-400">
              فقط تماس‌هایی که شماره موبایل یا داخلی شما یک سمت آن باشد.
            </p>
          ) : null}
        </div>
        <CallUploadForm onUploaded={() => void load(applied, null)} />
      </div>
      <form
        className="card grid gap-3 md:grid-cols-7"
        onSubmit={(event) => {
          event.preventDefault();
          if (appliedFiltersUnchanged) {
            setFilters(EMPTY);
            setApplied(EMPTY);
          } else {
            setApplied(filters);
          }
        }}
      >
        <div>
          <label className="label">از تاریخ</label>
          <JalaliDatePicker
            value={filters.from}
            onChange={(from) => setFilters({ ...filters, from })}
            placeholder="تاریخ شروع"
          />
        </div>
        <div>
          <label className="label">تا تاریخ</label>
          <JalaliDatePicker
            value={filters.to}
            onChange={(to) => setFilters({ ...filters, to })}
            placeholder="تاریخ پایان"
          />
        </div>
        <div>
          <label className="label">جست‌وجو در متن</label>
          <input
            className="input"
            value={filters.q}
            onChange={(event) => setFilters({ ...filters, q: event.target.value })}
          />
        </div>
        <div>
          <label className="label">شماره</label>
          <input
            className="input"
            dir="ltr"
            value={fmt.digits(filters.number)}
            onChange={(event) => setFilters({ ...filters, number: fmt.latinDigits(event.target.value) })}
          />
        </div>
        <div>
          <label className="label">قصد</label>
          <select
            className="input"
            value={filters.intent}
            onChange={(event) => setFilters({ ...filters, intent: event.target.value })}
          >
            <option value="">همه</option>
            {Object.entries(INTENT_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">احساس</label>
          <select
            className="input"
            value={filters.sentiment}
            onChange={(event) => setFilters({ ...filters, sentiment: event.target.value })}
          >
            <option value="">همه</option>
            {Object.entries(SENTIMENT_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <button
            className={`${appliedFiltersUnchanged ? "btn-ghost text-rose-700" : "btn"} min-h-[42px] w-full`}
          >
            {appliedFiltersUnchanged ? "پاک کردن" : "اعمال فیلتر"}
          </button>
        </div>
      </form>

      <ErrorBox message={error} />

      <div className="card">
        {items.length === 0 && loading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty />
        ) : (
          <table className="table" dir="rtl">
            <thead>
              <tr>
                <th>زمان</th>
                <th>تماس‌گیرنده</th>
                <th>شماره مقصد</th>
                <th>مدت</th>
                <th>خلاصه</th>
                <th>قصد</th>
                <th>احساس</th>
                <th>وضعیت</th>
                {canDelete ? <th aria-label="حذف" /> : null}
              </tr>
            </thead>
            <tbody>
              {items.map((call) => (
                <tr
                  key={call.id}
                  className="table-row-link"
                  role="link"
                  tabIndex={0}
                  onClick={() => navigate(`/calls/${call.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      navigate(`/calls/${call.id}`);
                    }
                  }}
                >
                  <td>{fmt.dateTime(call.started_at)}</td>
                  <td dir="ltr">{call.caller_number ? fmt.digits(call.caller_number) : "—"}</td>
                  <td dir="ltr">{call.dialed_number ? fmt.digits(call.dialed_number) : "—"}</td>
                  <td>{fmt.duration(call.duration_ms)}</td>
                  <SummaryCell summary={call.summary} />
                  <td>{call.intent ? (INTENT_LABELS[call.intent] ?? call.intent) : "—"}</td>
                  <td dir="rtl">
                    <span className="inline-flex flex-wrap items-center gap-1" dir="rtl">
                      <SentimentBadge sentiment={call.sentiment} />
                      <TrajectoryBadge trajectory={call.sentiment_trajectory} />
                    </span>
                  </td>
                  <td>
                    <StatusBadge status={call.status} />
                  </td>
                  {canDelete ? (
                    <td>
                      <button
                        type="button"
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label="حذف تماس"
                        title="حذف تماس"
                        disabled={deletingId === call.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          void deleteCall(call);
                        }}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <TrashIcon />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Pagination page={pageIndex + 1} hasPrevious={pageIndex > 0} hasNext={Boolean(cursor)} total={total} loading={loading} onPrevious={previousPage} onNext={nextPage} />
      </div>
    </div>
  );
}
