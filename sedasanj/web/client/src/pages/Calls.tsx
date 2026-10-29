import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fmt, INTENT_LABELS, query, request, SENTIMENT_LABELS, STATUS_LABELS } from "../api";
import { isOperator, isOrgAdmin, useAuth } from "../auth";
import { Empty, ErrorBox, Pagination, SentimentBadge, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { FilterSelect, useFilterBar, type FilterBarField } from "@cbi/web-shared/components/FilterBar";
import type { CallPage, CallSummary } from "../types";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import CallUploadForm from "./CallUploadForm";
import ConfirmDialog from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";

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

/** Phone number with the phonebook title (when there is one) above it. */
function PartyCell({ number, name }: { number: string | null; name?: string | null }) {
  return (
    <td dir="ltr">
      {name ? (
        <div className="text-left text-xs font-bold">
          <bdi>{name}</bdi>
        </div>
      ) : null}
      <div>{number ? fmt.digits(number) : "—"}</div>
    </td>
  );
}

function callColumns(canDelete: boolean): SkeletonColumn[] {
  return [
    { label: "زمان", width: "8.5rem" },
    { label: "تماس‌گیرنده", width: "6.5rem", dir: "ltr" },
    { label: "شماره مقصد", width: "5rem", dir: "ltr" },
    { label: "مدت", width: "2.5rem" },
    { label: "خلاصه", width: "16rem", cellClassName: "max-w-sm truncate" },
    { label: "قصد", width: "4.5rem" },
    { label: "احساس", kind: "badges", dir: "rtl" },
    { label: "وضعیت", kind: "badge" },
    ...(canDelete ? [{ label: null, ariaLabel: "حذف", kind: "button" as const }] : []),
  ];
}

const FIRST_LOAD_ROWS = 10;
const EMPTY_PREVIOUS_ROWS = 5;

/** Owns the calls data: only this subtree reloads when filters or the page change. */
const CallsTableSection = memo(function CallsTableSection({
  applied,
  pageIndex,
  reloadKey,
  canDelete,
  onPage,
}: {
  applied: Filters;
  pageIndex: number;
  reloadKey: number;
  canDelete: boolean;
  onPage: (page: number) => void;
}) {
  const navigate = useNavigate();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<CallSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const appliedKey = JSON.stringify(applied);

  const calls = useResource<CallPage>(async (signal) => {
    const response = await request<CallPage>(`/v1/calls${query({ ...applied, offset: pageIndex * PAGE_SIZE, limit: PAGE_SIZE })}`, { signal });
    if (response.total > 0 && pageIndex >= response.pages) {
      // Past the last page: move to it; this request is superseded by the one the new URL triggers.
      onPage(response.pages);
      return new Promise<CallPage>(() => {});
    }
    return response;
  }, [appliedKey, pageIndex, reloadKey]);

  const items = calls.data?.items ?? [];
  const pages = calls.data?.pages ?? 1;
  const columns = callColumns(canDelete);

  useEffect(() => {
    if (!items.some((call) => call.processing)) return;
    const timer = window.setInterval(() => calls.reload({ silent: true }), 3000);
    return () => window.clearInterval(timer);
  }, [items, calls.reload]);

  async function deleteCall(call: CallSummary) {
    setDeletingId(call.id);
    setActionError(null);
    try {
      await request<void>(`/v1/calls/${call.id}`, { method: "DELETE" });
      setDeleteCandidate(null);
      if (items.length === 1 && pageIndex > 0) onPage(pageIndex);
      else calls.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <ErrorBox message={calls.error ?? actionError} />

      <div className="card">
        {calls.loading ? (
          <SkeletonTable columns={columns} rows={calls.data ? Math.min(items.length || EMPTY_PREVIOUS_ROWS, PAGE_SIZE) : FIRST_LOAD_ROWS} />
        ) : items.length === 0 ? (
          <Empty />
        ) : (
          <table className="table" dir="rtl">
            <thead>
              <tr>
                {columns.map((column, index) => (
                  <th key={index} aria-label={column.ariaLabel}>{column.label}</th>
                ))}
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
                  <PartyCell number={call.caller_number} name={call.caller_name} />
                  <PartyCell number={call.dialed_number} name={call.dialed_name} />
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
                    <StatusBadge status={call.call_type === "answered" ? call.status : call.call_type} />
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
          total={calls.data?.total}
          loading={calls.loading}
          onPrevious={() => onPage(pageIndex)}
          onNext={() => onPage(pageIndex + 2)}
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
    </>
  );
});

export default function Calls() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const canDelete = isOrgAdmin(session?.role);
  const searchKey = searchParams.toString();
  const applied = useMemo(() => filtersFromSearch(new URLSearchParams(searchKey)), [searchKey]);
  const pageIndex = pageFromSearch(new URLSearchParams(searchKey)) - 1;
  const [filters, setFilters] = useState<Filters>(applied);
  const [reloadKey, setReloadKey] = useState(0);
  const hasAppliedFilters = Object.values(applied).some(Boolean);

  useEffect(() => {
    setFilters(applied);
  }, [applied]);

  function updateSearch(next: Filters, page = 1) {
    setSearchParams(searchFromFilters(next, page));
  }

  // Stable between keystrokes in the filter fields, so the table section is not re-rendered by them.
  const goToPage = useCallback((page: number) => setSearchParams(searchFromFilters(applied, page)), [applied, setSearchParams]);

  function resetField(key: keyof Filters) {
    setFilters((current) => ({ ...current, [key]: "" }));
    if (applied[key]) updateSearch({ ...applied, [key]: "" });
  }

  const callFilterFields: FilterBarField[] = [
    {
      id: "from",
      label: "از تاریخ",
      active: Boolean(filters.from),
      onRemove: () => resetField("from"),
      control: <JalaliDatePicker value={filters.from} onChange={(from) => setFilters({ ...filters, from })} placeholder="انتخاب تاریخ" />,
    },
    {
      id: "to",
      label: "تا تاریخ",
      active: Boolean(filters.to),
      onRemove: () => resetField("to"),
      control: <JalaliDatePicker value={filters.to} onChange={(to) => setFilters({ ...filters, to })} placeholder="انتخاب تاریخ" />,
    },
    {
      id: "q",
      label: "جست‌وجو در متن",
      active: Boolean(filters.q),
      onRemove: () => resetField("q"),
      control: <input className="input" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} />,
    },
    {
      id: "number",
      label: "شماره",
      active: Boolean(filters.number),
      onRemove: () => resetField("number"),
      control: <input className="input" dir="ltr" value={fmt.digits(filters.number)} onChange={(event) => setFilters({ ...filters, number: fmt.latinDigits(event.target.value) })} />,
    },
    {
      id: "intent",
      label: "قصد",
      active: Boolean(filters.intent),
      onRemove: () => resetField("intent"),
      control: <FilterSelect value={filters.intent} onChange={(intent) => setFilters({ ...filters, intent })} options={Object.entries(INTENT_LABELS).map(([value, label]) => ({ value, label }))} />,
    },
    {
      id: "sentiment",
      label: "احساس",
      active: Boolean(filters.sentiment),
      onRemove: () => resetField("sentiment"),
      control: <FilterSelect value={filters.sentiment} onChange={(sentiment) => setFilters({ ...filters, sentiment })} options={Object.entries(SENTIMENT_LABELS).map(([value, label]) => ({ value, label }))} />,
    },
    {
      id: "status",
      label: "وضعیت",
      active: Boolean(filters.status),
      onRemove: () => resetField("status"),
      control: (
        <FilterSelect
          value={filters.status}
          onChange={(status) => setFilters({ ...filters, status })}
          options={[
            { value: "answered", label: "پاسخ‌داده‌شده" },
            ...Object.entries(STATUS_LABELS).filter(([key]) => key !== "missed" && key !== "answered").map(([value, label]) => ({ value, label })),
          ]}
        />
      ),
    },
    {
      id: "direction",
      label: "جهت تماس",
      active: Boolean(filters.direction),
      onRemove: () => resetField("direction"),
      control: <FilterSelect value={filters.direction} onChange={(direction) => setFilters({ ...filters, direction })} options={[{ value: "inbound", label: "ورودی" }, { value: "outbound", label: "خروجی" }]} />,
    },
  ];

  const filterBar = useFilterBar({
    hasActive: hasAppliedFilters || Object.values(filters).some(Boolean),
    onClear: () => {
      setFilters(EMPTY);
      updateSearch(EMPTY);
    },
    onApply: () => updateSearch(filters),
    fields: callFilterFields,
  });

  return (
    <div className="space-y-4">
      <PageHeader title="تماس‌ها" description={operator ? "فقط تماس‌هایی که شماره موبایل یا داخلی شما یک سمت آن باشد." : "فهرست و جست‌وجوی مکالمات سازمان"} actions={<div className="flex flex-wrap items-end justify-end gap-3"><CallUploadForm onUploaded={() => setReloadKey((key) => key + 1)} />{filterBar.toolbar}</div>} />
      {filterBar.fields}
      <CallsTableSection applied={applied} pageIndex={pageIndex} reloadKey={reloadKey} canDelete={canDelete} onPage={goToPage} />
    </div>
  );
}
