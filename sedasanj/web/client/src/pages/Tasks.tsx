import { useCallback, useEffect, useMemo, useState } from "react";
import { request } from "../api";
import { CAN_EDIT_TASKS, isOperator, useAuth } from "../auth";
import FollowUpTaskCard from "../components/FollowUpTaskCard";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import type { TaskBoard } from "../types";

type View = "today" | "upcoming" | "open" | "done" | "all";

const VIEWS: { id: View; label: string }[] = [
  { id: "today", label: "امروز" },
  { id: "upcoming", label: "روزهای دیگر" },
  { id: "open", label: "انجام‌نشده" },
  { id: "done", label: "انجام‌شده" },
  { id: "all", label: "همه" },
];

export default function Tasks() {
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const canEdit = Boolean(session && CAN_EDIT_TASKS.includes(session.role));
  const [view, setView] = useState<View>("today");
  const [board, setBoard] = useState<TaskBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setBoard(await request<TaskBoard>("/v1/tasks"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpdated() {
    try {
      const next = await request<TaskBoard>("/v1/tasks");
      setBoard(next);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const counts = useMemo(
    () => ({
      today: board?.today_count ?? 0,
      upcoming: board?.upcoming_count ?? 0,
      open: board?.open_count ?? 0,
      done: board?.completed_count ?? 0,
      all: (board?.open_count ?? 0) + (board?.completed_count ?? 0),
    }),
    [board],
  );

  const showToday = view === "today" || view === "open" || view === "all";
  const showUpcoming = view === "upcoming" || view === "open" || view === "all";
  const showDone = view === "done" || view === "all";
  const empty =
    Boolean(board) &&
    ((view === "today" && board!.today.length === 0) ||
      (view === "upcoming" && board!.upcoming.length === 0) ||
      (view === "open" && board!.open_count === 0) ||
      (view === "done" && board!.completed.length === 0) ||
      (view === "all" && counts.all === 0));

  return (
    <div className="space-y-4 text-[#000000]">
      <div>
        <h1 className="text-lg font-bold">کارهای قابل پیگیری</h1>
        <p className="mt-1 text-xs text-slate-400">
          کارهای استخراج‌شده از مکالمات تا وقتی انجام نشوند هر روز به فهرست امروز منتقل می‌شوند.
          {operator
            ? " فقط کارهای تماس‌هایی را می‌بینید که شماره موبایل یا داخلی شما یکی از طرفین آن باشد."
            : null}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {VIEWS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
              view === item.id
                ? "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]"
                : "border-[#B2AC88] bg-[#F2F0EF] text-[#4B6E48] hover:bg-[#B2AC88] hover:text-black"
            }`}
            onClick={() => setView(item.id)}
          >
            {item.label}
            <span className={`mr-1 text-xs ${view === item.id ? "text-[#F2F0EF]" : "text-[#898989]"}`}>
              ({fmtCount(counts[item.id])})
            </span>
          </button>
        ))}
      </div>

      <ErrorBox message={error} />

      {loading && !board ? (
        <Loading />
      ) : empty ? (
        <div className="card">
          <Empty>
            {view === "today"
              ? "برای امروز کار بازی باقی نمانده است."
              : view === "upcoming"
                ? "کار زمان‌بندی‌شده‌ای برای روزهای بعد نیست."
                : view === "done"
                  ? "هنوز کاری انجام‌شده ثبت نشده است."
                  : "کاری ثبت نشده است."}
          </Empty>
        </div>
      ) : (
        <div className="space-y-6">
          {showToday ? (
            <section className="card overflow-visible">
              <h2 className="mb-1 font-bold">امروز</h2>
              <p className="mb-4 text-xs text-slate-400">
                شامل کارهای بدون موعد و کارهای عقب‌افتاده که به امروز منتقل شده‌اند.
              </p>
              {board?.today.length ? (
                <ul className="space-y-2">
                  {board.today.map((task) => (
                    <FollowUpTaskCard
                      key={task.id}
                      task={task}
                      canEdit={canEdit}
                      onUpdated={() => void handleUpdated()}
                    />
                  ))}
                </ul>
              ) : (
                <Empty>کاری برای امروز نیست.</Empty>
              )}
            </section>
          ) : null}

          {showUpcoming ? (
            <section className="card overflow-visible">
              <h2 className="mb-1 font-bold">روزهای دیگر</h2>
              <p className="mb-4 text-xs text-slate-400">کارهایی که موعدشان بعد از امروز است.</p>
              {board?.upcoming.length ? (
                <div className="space-y-5">
                  {board.upcoming.map((day) => (
                    <div key={day.date}>
                      <h3 className="mb-2 text-sm font-semibold text-slate-600">{formatDay(day.date)}</h3>
                      <ul className="space-y-2">
                        {day.items.map((task) => (
                          <FollowUpTaskCard
                            key={task.id}
                            task={task}
                            canEdit={canEdit}
                            onUpdated={() => void handleUpdated()}
                          />
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty>کار زمان‌بندی‌شده‌ای برای روزهای بعد نیست.</Empty>
              )}
            </section>
          ) : null}

          {showDone ? (
            <section className="card overflow-visible">
              <h2 className="mb-4 font-bold">انجام‌شده</h2>
              {board?.completed.length ? (
                <ul className="space-y-2">
                  {board.completed.map((task) => (
                    <FollowUpTaskCard
                      key={task.id}
                      task={task}
                      canEdit={canEdit}
                      onUpdated={() => void handleUpdated()}
                    />
                  ))}
                </ul>
              ) : (
                <Empty>کاری انجام نشده است.</Empty>
              )}
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}

function fmtCount(value: number): string {
  return new Intl.NumberFormat("fa-IR").format(value);
}

function formatDay(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const utc = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
  return utc.toLocaleDateString("fa-IR-u-ca-persian", {
    timeZone: "UTC",
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}
