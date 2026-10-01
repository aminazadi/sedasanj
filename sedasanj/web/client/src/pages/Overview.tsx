import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { chart } from "@cbi/web-shared/theme";
import { fmt, request, SENTIMENT_LABELS, TRAJECTORY_LABELS } from "../api";
import { isOperator, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, SentimentBadge, Stat, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import type { AnalyticsSummary, Balance, CallPage, TaskBoard } from "../types";

const COLORS: Record<string, string> = {
  angry: chart.danger,
  sad: chart.secondary,
  neutral: chart.warning,
  satisfied: chart.cyan,
  happy: chart.success,
};

const TRAJECTORY_COLORS: Record<string, string> = {
  improved: chart.success,
  worsened: chart.danger,
  stable: chart.violet,
};

export default function Overview() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [recent, setRecent] = useState<CallPage | null>(null);
  const [tasks, setTasks] = useState<TaskBoard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const from = new Date(Date.now() - 30 * 86400000).toISOString();
    const requests: Promise<unknown>[] = [
      request<AnalyticsSummary>(`/v1/analytics/summary?from=${from}`),
      request<CallPage>("/v1/calls?limit=10"),
      request<TaskBoard>("/v1/tasks"),
    ];
    if (!operator) {
      requests.unshift(request<Balance>("/v1/billing/balance"));
    }
    Promise.all(requests)
      .then((results) => {
        if (operator) {
          setSummary(results[0] as AnalyticsSummary);
          setRecent(results[1] as CallPage);
          setTasks(results[2] as TaskBoard);
          setBalance(null);
        } else {
          setBalance(results[0] as Balance);
          setSummary(results[1] as AnalyticsSummary);
          setRecent(results[2] as CallPage);
          setTasks(results[3] as TaskBoard);
        }
      })
      .catch((err) => setError(err.message));
  }, [operator]);

  if (error) return <ErrorBox message={error} />;
  if (!summary || !recent || !tasks || (!operator && !balance)) return <Loading />;

  const pie = summary.sentiments.map((bucket) => ({
    name: SENTIMENT_LABELS[bucket.key] ?? bucket.key,
    key: bucket.key,
    value: bucket.count,
  }));
  const trajectoryPie = (summary.caller_trajectories ?? []).map((bucket) => ({
    name: TRAJECTORY_LABELS[bucket.key] ?? bucket.key,
    key: bucket.key,
    value: bucket.count,
  }));

  return (
    <div className="space-y-6">
      {operator ? (
        <p className="text-sm text-slate-500">
          در پنل اپراتور فقط تماس‌هایی را می‌بینید که شماره موبایل یا داخلی شما یکی از طرفین آن بوده است.
        </p>
      ) : null}
      <div className={`grid gap-4 ${operator ? "md:grid-cols-3" : "md:grid-cols-5"}`}>
        {operator || !balance ? null : (
          <>
            <Stat title="اعتبار (تومان)" value={fmt.toman(balance.toman)} />
            <Stat title="اعتبار (دقیقه)" value={fmt.int(balance.minutes)} />
          </>
        )}
        <Stat title="تماس‌های ۳۰ روز" value={fmt.int(summary.total_calls)} />
        <Stat
          title="دقایق تحلیل‌شده"
          value={fmt.int(summary.total_minutes)}
          hint={
            operator || !balance
              ? undefined
              : `نرخ: ${fmt.toman(balance.price_per_minute_toman)} بر دقیقه`
          }
        />
        <Link to="/tasks" className="block transition hover:opacity-90">
          <Stat
            title="کارهای امروز"
            value={fmt.int(tasks.today_count)}
            hint={`${fmt.int(tasks.open_count)} کار باز`}
          />
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-bold">توزیع احساس مشتری</h2>
          {pie.length === 0 ? (
            <Empty />
          ) : (
            <div className="h-64">
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={pie} dataKey="value" nameKey="name" innerRadius={50} outerRadius={90} paddingAngle={3} stroke="#F2F0EF" strokeWidth={2}>
                    {pie.map((slice) => (
                      <Cell key={slice.key} fill={COLORS[slice.key] ?? chart.primary} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => fmt.int(Number(value))} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="mb-3 font-bold">تغییر احساس مشتری</h2>
          {trajectoryPie.length === 0 ? (
            <Empty />
          ) : (
            <div className="h-64">
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={trajectoryPie} dataKey="value" nameKey="name" innerRadius={50} outerRadius={90} paddingAngle={3} stroke="#F2F0EF" strokeWidth={2}>
                    {trajectoryPie.map((slice) => (
                      <Cell key={slice.key} fill={TRAJECTORY_COLORS[slice.key] ?? chart.primary} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => fmt.int(Number(value))} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-bold">۱۰ تماس آخر</h2>
          <Link to="/calls" className="text-sm text-slate-700 transition hover:text-slate-900">
            همه تماس‌ها
          </Link>
        </div>
          {recent.items.length === 0 ? (
            <Empty />
          ) : (
            <table className="table" dir="rtl">
              <thead>
                <tr>
                  <th>زمان</th>
                  <th>شماره</th>
                  <th>مدت</th>
                  <th>خلاصه</th>
                  <th>وضعیت</th>
                  <th>احساس</th>
                  <th>تغییر</th>
                </tr>
              </thead>
              <tbody>
                {recent.items.map((call) => (
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
                    <td>{fmt.duration(call.duration_ms)}</td>
                    <SummaryCell summary={call.summary} />
                    <td>
                      <StatusBadge status={call.status} />
                    </td>
                    <td dir="rtl">
                      <span dir="rtl">
                        <SentimentBadge sentiment={call.sentiment} />
                      </span>
                    </td>
                    <td>
                      <TrajectoryBadge trajectory={call.sentiment_trajectory} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
    </div>
  );
}
