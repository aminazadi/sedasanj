import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fmt, INTENT_LABELS, query, request, SENTIMENT_LABELS, STATUS_LABELS } from "../api";
import { isOperator, isOrgAdmin, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination, SentimentBadge, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import TableFilters from "@cbi/web-shared/components/TableFilters";
import type { CallPage, CallSummary } from "../types";
import CallUploadForm from "./CallUploadForm";
import ConfirmDialog from "../components/ConfirmDialog";

interface Filters {
  from: string;
  to: string;
  q: string;
  intent: string;
  sentiment: string;
  number: string;
  status: string;
  direction: string;
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

const EMPTY: Filters = {
  from: "",
  to: "",
  q: "",
  intent: "",
  sentiment: "",
  number: "",
  status: "",
  direction: "",
};
const PAGE_SIZE = 25;

function filtersFromSearch(search: URLSearchParams): Filters {
  return {
    from: search.get("from") ?? "",
    to: search.get("to") ?? "",
    q: search.get("q") ?? "",
    intent: search.get("intent") ?? "",
    sentiment: search.get("sentiment") ?? "",
    number: search.get("number") ?? "",
    status: search.get("status") ?? "",
    direction: search.get("direction") ?? "",
  };
}

function pageFromSearch(search: URLSearchParams): number {
  const page = Number(search.get("page") ?? "1");
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

function searchFromFilters(filters: Filters, page = 1): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, rawValue] of Object.entries(filters)) {
    const value = rawValue.trim();
    if (value) params.set(key, value);
  }
  if (page > 1) params.set("page", String(page));
  return params;
}

export default function Calls() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const canDelete = isOrgAdmin(session?.role);
  const searchKey = searchParams.toString();
  const applied = useMemo(() => filtersFromSearch(new URLSearchParams(searchKey)), [searchKey]);
  const pageIndex = pageFromSearch(new URLSearchParams(searchKey)) - 1;
  const [filters, setFilters] = useState<Filters>(applied);
  const [items, setItems] = useState<CallSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<CallSummary | null>(null);
  const hasAppliedFilters = Object.values(applied).some(Boolean);

  const load = useCallback(
    async (next: Filters, pageNumber: number, silent = false) => {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const response = await request<CallPage>(
          `/v1/calls${query({
            ...next,
            offset: pageNumber * PAGE_SIZE,
            limit: PAGE_SIZE,
          })}`,
        );
        if (response.total > 0 && pageNumber >= response.pages) {
          setSearchParams(searchFromFilters(next, response.pages), { replace: true });
          return;
        }
        setItems(response.items);
        setTotal(response.total);
        setPages(response.pages);
      } catch (err) {
        if (!silent) setError((err as Error).message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [setSearchParams],
  );

  useEffect(() => {
    setFilters(applied);
    void load(applied, pageIndex);
  }, [applied, load, pageIndex]);

  useEffect(() => {
    if (!items.some((call) => call.processing)) return;
    const timer = window.setInterval(() => {
      void load(applied, pageIndex, true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [applied, items, load, pageIndex]);

  async function deleteCall(call: CallSummary) {
    setDeletingId(call.id);
    setError(null);
    try {
      await request<void>(`/v1/calls/${call.id}`, { method: "DELETE" });
      setDeleteCandidate(null);
      if (items.length === 1 && pageIndex > 0) {
        setSearchParams(searchFromFilters(applied, pageIndex));
      } else {
        await load(applied, pageIndex);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  function updateSearch(next: Filters, page = 1) {
    setSearchParams(searchFromFilters(next, page));
  }

  function goToPage(page: number) {
    updateSearch(applied, Math.min(Math.max(page, 1), pages));
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
        <CallUploadForm onUploaded={() => void load(applied, pageIndex)} />
      </div>
      <TableFilters>
      <form
        className="grid gap-3 md:grid-cols-7"
        onSubmit={(event) => {
          event.preventDefault();
          updateSearch(filters);
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
        <div>
          <label className="label">وضعیت</label>
          <select
            className="input"
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value })}
          >
            <option value="">همه</option>
            {Object.entries(STATUS_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">جهت تماس</label>
          <select
            className="input"
            value={filters.direction}
            onChange={(event) => setFilters({ ...filters, direction: event.target.value })}
          >
            <option value="">همه</option>
            <option value="inbound">ورودی</option>
            <option value="outbound">خروجی</option>
          </select>
        </div>
        <div className="flex items-end gap-2 md:col-span-2">
          <button className="btn min-h-[42px] flex-1">اعمال فیلتر</button>
          <button
            type="button"
            className="btn-ghost min-h-[42px] flex-1"
            disabled={!hasAppliedFilters && !Object.values(filters).some(Boolean)}
            onClick={() => {
              setFilters(EMPTY);
              updateSearch(EMPTY);
            }}
          >
            پاک کردن
          </button>
        </div>
      </form>
      </TableFilters>

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
                          setDeleteCandidate(call);
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
        <Pagination
          page={pageIndex + 1}
          hasPrevious={pageIndex > 0}
          hasNext={pageIndex + 1 < pages}
          total={total}
          loading={loading}
          onPrevious={() => goToPage(pageIndex)}
          onNext={() => goToPage(pageIndex + 2)}
        />
      </div>
      <ConfirmDialog
        open={Boolean(deleteCandidate)}
        title="حذف تماس"
        description="این تماس، فایل صوتی، متن، تحلیل‌ها و کارهای مرتبط برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست."
        confirmLabel="حذف تماس"
        destructive
        busy={Boolean(deletingId)}
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => { if (deleteCandidate) void deleteCall(deleteCandidate); }}
      />
    </div>
  );
}
