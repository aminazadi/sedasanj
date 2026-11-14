import BulkActions, { SelectionCheckbox, useBulkSelection } from "../components/BulkActions";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, MEETING_STATUS_LABELS, query, request } from "../api";
import { CAN_MANAGE_MEETINGS, isOrgAdmin, useAuth } from "../auth";
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
  const [bulkBusy, setBulkBusy] = useState(false);
  const { selected, setSelected, toggle } = useBulkSelection(`${appliedKey}:${pageIndex}:${PAGE_SIZE}`);
  const { session } = useAuth();
  const canManage = CAN_MANAGE_MEETINGS.includes(session?.role ?? "");

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
    if (bulkBusy || !items.some((meeting) => isMeetingActive(meeting.status))) return;
    const timer = window.setInterval(() => meetings.reload({ silent: true }), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [bulkBusy, items, meetings.reload]);

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
          disabled={bulkBusy || meetings.loading}
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
        <BulkActions disabled={meetings.loading} selected={selected} setSelected={setSelected} onBusy={setBulkBusy} onComplete={() => meetings.reload()} actions={[
          ...(canManage ? [
            { label: "بازتحلیل صورت‌جلسه", eligible: (id: string) => items.some((meeting) => meeting.id === id && meeting.status === "complete"), execute: (id: string) => request(`/v1/meetings/${id}/reanalyze`, { method: "POST" }) },
            { label: "تلاش مجدد پردازش", eligible: (id: string) => items.some((meeting) => meeting.id === id && ["failed_retryable", "failed_terminal"].includes(meeting.status)), execute: (id: string) => request(`/v1/meetings/${id}/retry`, { method: "POST" }) },
          ] : []),
          { label: "حذف", destructive: true, eligible: (id) => items.some((meeting) => meeting.id === id && canDelete(meeting)), execute: (id) => request(`/v1/meetings/${id}`, { method: "DELETE" }) },
        ]} />
        {meetings.loading ? (
          <SkeletonTable columns={columns} rows={meetings.data ? Math.min(items.length || EMPTY_PREVIOUS_ROWS, PAGE_SIZE) : FIRST_LOAD_ROWS} />
        ) : items.length === 0 ? (
          <Empty>هنوز جلسه‌ای ثبت نشده است. برای ضبط جلسه، <Link className="underline" to="/account-settings?tab=integrations">اپ جلسه‌نگار را متصل کنید</Link>.</Empty>
        ) : (
          <table className="table" dir="rtl">
            <thead>
              <tr>
                <th><SelectionCheckbox label="انتخاب همه موارد این صفحه" checked={items.length > 0 && items.every((item) => selected.includes(item.id))} mixed={items.some((item) => selected.includes(item.id)) && !items.every((item) => selected.includes(item.id))} disabled={bulkBusy} onChange={() => setSelected(items.every((item) => selected.includes(item.id)) ? [] : items.map((item) => item.id))} /></th>
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
                  <td><SelectionCheckbox label={`انتخاب مورد ${meeting.id}`} checked={selected.includes(meeting.id)} disabled={bulkBusy} onChange={() => toggle(meeting.id)} /></td>
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
                        disabled={bulkBusy || deletingId === meeting.id}
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
          loading={bulkBusy || meetings.loading}
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
  const [findingApp, setFindingApp] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const hasAppliedFilters = Object.values(applied).some(Boolean);

  async function downloadApp() {
    setFindingApp(true);
    setDownloadError(null);
    try {
      const { download_path } = await request<{ download_path: string }>("/v1/meetings/app-download", {
        headers: { "Cache-Control": "no-cache" },
      });
      const link = document.createElement("a");
      link.href = download_path;
      link.download = "";
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      setDownloadError(error instanceof ApiError && error.code === "jalase_negar_release_not_found"
        ? "هنوز نسخه‌ای از جلسه‌نگار منتشر نشده است. بعداً دوباره بررسی کنید."
        : "دریافت فایل جلسه‌نگار ممکن نشد. چند دقیقه دیگر دوباره تلاش کنید.");
    } finally {
      setFindingApp(false);
    }
  }

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
        actions={
          <div className="flex flex-wrap items-end justify-end gap-3">
            {filterBar.toolbar}
            <button type="button" className="btn-ghost min-h-[42px] rounded-none px-3" disabled={findingApp} onClick={downloadApp}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
                <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" />
              </svg>
              {findingApp ? "در حال بررسی نسخه…" : "دانلود اپلیکیشن"}
            </button>
          </div>
        }
      />
      <ErrorBox message={downloadError} className="!rounded-none" />
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
