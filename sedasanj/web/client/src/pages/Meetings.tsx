import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fmt, MEETING_STATUS_LABELS, query, request } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import { Empty, ErrorBox, Pagination, SummaryCell } from "../components/Widgets";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { FilterSelect, useFilterBar, type FilterBarField } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import ConfirmDialog from "../components/ConfirmDialog";
import MeetingStatusBadge from "../components/MeetingStatusBadge";
import { PageHeader } from "../components/PageHeader";
import { useTablePageSize } from "../lib/useTablePagination";
import { isMeetingActive, meetingFiltersFromSearch, meetingPageFromSearch, meetingProgress, searchFromMeetingFilters } from "../lib/meetingsHelpers.mjs";
import type { MeetingFilters } from "../lib/meetingsHelpers.mjs";
import type { MeetingListItem, MeetingPage, Page, User } from "../types";

const EMPTY: MeetingFilters = { q: "", status: "", owner_id: "", from: "", to: "" };
const FIRST_LOAD_ROWS = 10;
const EMPTY_PREVIOUS_ROWS = 5;
const POLL_INTERVAL_MS = 3000;

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

function meetingColumns(showOwner: boolean): SkeletonColumn[] {
  return [
    { label: "عنوان", width: "12rem", cellClassName: "max-w-xs truncate" },
    { label: "زمان", width: "8.5rem" },
    { label: "مدت", width: "2.5rem" },
    { label: "گوینده‌ها", width: "3.5rem" },
    ...(showOwner ? [{ label: "برگزارکننده", width: "7rem" }] : []),
    { label: "خلاصه", width: "16rem", cellClassName: "max-w-sm truncate" },
    { label: "وضعیت", kind: "badge" as const },
    { label: null, ariaLabel: "حذف", kind: "button" as const },
  ];
}

/** Owns the meetings data: only this subtree reloads when filters or the page change. */
const MeetingsTableSection = memo(function MeetingsTableSection({
  applied,
  pageIndex,
  refreshTarget,
  showOwner,
  canDelete,
  onPage,
}: {
  applied: MeetingFilters;
  pageIndex: number;
  refreshTarget: HTMLDivElement | null;
  showOwner: boolean;
  canDelete: (meeting: MeetingListItem) => boolean;
  onPage: (page: number) => void;
}) {
  const [PAGE_SIZE] = useTablePageSize();
  const navigate = useNavigate();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<MeetingListItem | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const appliedKey = JSON.stringify(applied);

  const meetings = useResource<MeetingPage>(async (signal) => {
    const response = await request<MeetingPage>(`/v1/meetings${query({ ...applied, page: pageIndex + 1, page_size: PAGE_SIZE })}`, { signal });
    if (response.total > 0 && pageIndex >= response.pages) {
      // Past the last page: move to it; this request is superseded by the one the new URL triggers.
      onPage(response.pages);
      return new Promise<MeetingPage>(() => {});
    }
    return response;
  }, [PAGE_SIZE, appliedKey, pageIndex]);

  const items = meetings.data?.items ?? [];
  const pages = meetings.data?.pages ?? 1;
  const columns = meetingColumns(showOwner);

  useEffect(() => {
    if (!items.some((meeting) => isMeetingActive(meeting.status))) return;
    const timer = window.setInterval(() => meetings.reload({ silent: true }), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [items, meetings.reload]);

  async function deleteMeeting(meeting: MeetingListItem) {
    setDeletingId(meeting.id);
    setActionError(null);
    try {
      await request<void>(`/v1/meetings/${meeting.id}`, { method: "DELETE" });
      setDeleteCandidate(null);
      if (items.length === 1 && pageIndex > 0) onPage(pageIndex);
      else meetings.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      {refreshTarget ? createPortal(
        <button
          type="button"
          className="btn inline-flex h-[42px] w-[42px] items-center justify-center p-0"
          onClick={() => meetings.reload()}
          disabled={meetings.loading}
          aria-busy={meetings.loading}
          aria-label={meetings.loading ? "در حال بروزرسانی جلسات" : "بروزرسانی جلسات"}
          title="بروزرسانی جلسات"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
            <path d="M20 7v5h-5M4 17v-5h5" />
            <path d="M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 17.9 17" />
          </svg>
        </button>,
        refreshTarget,
      ) : null}
      <ErrorBox message={meetings.error ?? actionError} />

      <div className="card">
        {meetings.loading ? (
          <SkeletonTable columns={columns} rows={meetings.data ? Math.min(items.length || EMPTY_PREVIOUS_ROWS, PAGE_SIZE) : FIRST_LOAD_ROWS} />
        ) : items.length === 0 ? (
          <Empty>هنوز جلسه‌ای ثبت نشده است. جلسه را با اپ جلسه‌نگار ضبط کنید؛ اتصال اپ از «پروفایل من» انجام می‌شود.</Empty>
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
              {items.map((meeting) => (
                <tr
                  key={meeting.id}
                  className="table-row-link"
                  role="link"
                  tabIndex={0}
                  onClick={() => navigate(`/meetings/${meeting.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      navigate(`/meetings/${meeting.id}`);
                    }
                  }}
                >
                  <td className="max-w-xs truncate font-bold">{meeting.title || "جلسه بدون عنوان"}</td>
                  <td>{fmt.dateTime(meeting.started_at)}</td>
                  <td>{meeting.duration_ms === null ? "—" : fmt.duration(meeting.duration_ms)}</td>
                  <td>{meeting.speaker_count > 0 ? fmt.int(meeting.speaker_count) : "—"}</td>
                  {showOwner ? <td>{meeting.owner_name ?? "—"}</td> : null}
                  <SummaryCell summary={meeting.summary} />
                  <td>
                    <span className="inline-flex flex-wrap items-center gap-2">
                      <MeetingStatusBadge status={meeting.status} />
                      {meeting.status === "processing" ? <span className="text-xs tabular-nums text-slate-500">{fmt.percent(meetingProgress(meeting.status, meeting.progress_pct))}</span> : null}
                    </span>
                  </td>
                  <td>
                    {canDelete(meeting) ? (
                      <button
                        type="button"
                        className="inline-flex h-8 w-8 items-center justify-center text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label="حذف جلسه"
                        title="حذف جلسه"
                        disabled={deletingId === meeting.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          setDeleteCandidate(meeting);
                        }}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <TrashIcon />
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Pagination
          page={pageIndex + 1}
          hasPrevious={pageIndex > 0}
          hasNext={pageIndex + 1 < pages}
          total={meetings.data?.total}
          loading={meetings.loading}
          onPrevious={() => onPage(pageIndex)}
          onNext={() => onPage(pageIndex + 2)}
        />
      </div>
      <ConfirmDialog
        open={Boolean(deleteCandidate)}
        title="حذف جلسه"
        description="این جلسه، فایل صوتی، متن، گوینده‌ها و صورت‌جلسه برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست."
        confirmLabel="حذف جلسه"
        destructive
        busy={Boolean(deletingId)}
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => { if (deleteCandidate) void deleteMeeting(deleteCandidate); }}
      />
    </>
  );
});

/** Meetings list; owner and org admin see a meeting, only an admin can filter by owner. */
export default function Meetings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);
  const searchKey = searchParams.toString();
  const pageSizeParam = searchParams.get("page_size");
  const applied = useMemo(() => meetingFiltersFromSearch(new URLSearchParams(searchKey)), [searchKey]);
  const pageIndex = meetingPageFromSearch(new URLSearchParams(searchKey)) - 1;
  const [filters, setFilters] = useState<MeetingFilters>(applied);
  const [refreshTarget, setRefreshTarget] = useState<HTMLDivElement | null>(null);
  const [search, setSearch] = useState(applied.q);
  const hasAppliedFilters = Object.values(applied).some(Boolean);

  const owners = useResource<Page<User> | null>(
    (signal) => (orgAdmin ? request<Page<User>>("/v1/auth/users?limit=200&offset=0", { signal }) : Promise.resolve(null)),
    [orgAdmin],
  );

  useEffect(() => {
    setFilters(applied);
    setSearch(applied.q);
  }, [applied]);

  // The search box applies itself shortly after typing stops, keeping the other applied filters.
  useEffect(() => {
    const next = search.trim();
    if (next === applied.q) return;
    const timer = window.setTimeout(() => setSearchParams(searchFromMeetingFilters({ ...applied, q: next }, 1, pageSizeParam)), 200);
    return () => window.clearTimeout(timer);
  }, [search, applied, pageSizeParam, setSearchParams]);

  function updateSearch(next: MeetingFilters, page = 1) {
    setSearchParams(searchFromMeetingFilters(next, page, pageSizeParam));
  }

  // Stable between keystrokes in the filter fields, so the table section is not re-rendered by them.
  const goToPage = useCallback((page: number) => setSearchParams(searchFromMeetingFilters(applied, page, pageSizeParam)), [applied, pageSizeParam, setSearchParams]);
  const userId = session?.userId;
  const canDelete = useCallback((meeting: MeetingListItem) => orgAdmin || meeting.owner_id === userId, [orgAdmin, userId]);

  function resetField(key: keyof MeetingFilters) {
    setFilters((current) => ({ ...current, [key]: "" }));
    if (applied[key]) updateSearch({ ...applied, [key]: "" });
  }

  const fields: FilterBarField[] = [
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
      id: "status",
      label: "وضعیت",
      active: Boolean(filters.status),
      onRemove: () => resetField("status"),
      control: <FilterSelect value={filters.status} onChange={(status) => setFilters({ ...filters, status })} options={Object.entries(MEETING_STATUS_LABELS).map(([value, label]) => ({ value, label }))} />,
    },
    {
      id: "owner_id",
      label: "برگزارکننده",
      active: Boolean(filters.owner_id),
      hidden: !orgAdmin,
      onRemove: () => resetField("owner_id"),
      control: <FilterSelect value={filters.owner_id} onChange={(owner_id) => setFilters({ ...filters, owner_id })} options={(owners.data?.items ?? []).map((user) => ({ value: user.id, label: user.display_name || user.email }))} />,
    },
  ];

  const filterBar = useFilterBar({
    hasActive: hasAppliedFilters || Object.values(filters).some(Boolean),
    onClear: () => {
      setFilters(EMPTY);
      updateSearch(EMPTY);
    },
    onApply: () => updateSearch(filters),
    fields,
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="جلسات"
        description={orgAdmin ? "جلسه‌های ضبط‌شده با اپ جلسه‌نگار برای همه‌ی اعضای سازمان" : "جلسه‌هایی که شما با اپ جلسه‌نگار ضبط کرده‌اید"}
        actions={<div className="flex flex-wrap items-end justify-end gap-3">{filterBar.toolbar}</div>}
      />
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input
            className="input w-full pr-10"
            type="search"
            value={search}
            maxLength={200}
            placeholder="جست‌وجو در عنوان، متن و صورت‌جلسه"
            aria-label="جست‌وجو در جلسات"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div ref={setRefreshTarget} className="flex shrink-0 items-center" />
      </div>
      {filterBar.fields}
      <MeetingsTableSection refreshTarget={refreshTarget} applied={applied} pageIndex={pageIndex} showOwner={orgAdmin} canDelete={canDelete} onPage={goToPage} />
    </div>
  );
}
