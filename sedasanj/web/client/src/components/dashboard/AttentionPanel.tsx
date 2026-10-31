import { Link } from "react-router-dom";
import { Icon } from "@iconify/react";
import angryIcon from "@iconify-icons/lucide/angry";
import chevronLeftIcon from "@iconify-icons/lucide/chevron-left";
import circleCheckIcon from "@iconify-icons/lucide/circle-check";
import clockAlertIcon from "@iconify-icons/lucide/clock-alert";
import eyeIcon from "@iconify-icons/lucide/eye";
import flameIcon from "@iconify-icons/lucide/flame";
import phoneMissedIcon from "@iconify-icons/lucide/phone-missed";
import trendingDownIcon from "@iconify-icons/lucide/trending-down";
import { fmt, query } from "../../api";
import type { KpiDashboard } from "../../types";
import { groupActions, type ActionGroup, type DashboardAction } from "./dashboardInsights.mjs";
import { DashboardCard } from "./DashboardCard";

const WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"];

interface GroupMeta {
  label: string;
  icon: typeof flameIcon;
  /** Page that lists every item of this group; omitted when the items themselves are the links. */
  link?: (range: { from: string; to: string }) => string;
  describe: (action: DashboardAction) => string;
}

const GROUPS: Record<string, GroupMeta> = {
  hot_opportunity: { label: "فرصت داغ بدون پیگیری", icon: flameIcon, describe: (item) => item.title || "فرصت فروش با احتمال بالا" },
  overdue_follow_up: { label: "پیگیری عقب‌افتاده", icon: clockAlertIcon, link: () => "/tasks", describe: (item) => (item.due_at ? `${item.title} · موعد ${fmt.calendarDate(item.due_at)}` : item.title) },
  operator_quality_drop: {
    label: "افت کیفیت اپراتور",
    icon: trendingDownIcon,
    link: () => "/operator-scores",
    describe: (item) => `${item.title}: کیفیت از ${fmt.decimal(Number(item.meta?.previous_value ?? 0))} به ${fmt.decimal(Number(item.meta?.value ?? 0))}`,
  },
  missed_peak: {
    label: "اوج تماس بی‌پاسخ",
    icon: phoneMissedIcon,
    link: (range) => `/calls${query({ from: range.from, to: range.to, status: "no_answer" })}`,
    describe: (item) => {
      const hour = Number(item.meta?.hour ?? 0);
      return `${WEEKDAYS[Number(item.meta?.weekday ?? 0)] ?? ""}‌ها ساعت ${fmt.int(hour)} تا ${fmt.int(hour + 1)} · ${fmt.decimal(Number(item.meta?.rate ?? 0))}٪ تماس‌ها بی‌پاسخ`;
    },
  },
  angry_customer: { label: "مشتری عصبانی بدون پیگیری", icon: angryIcon, link: (range) => `/calls${query({ from: range.from, to: range.to, sentiment: "angry" })}`, describe: (item) => item.title || "تماس با احساس خشم" },
  kpi_decline: { label: "افت نرخ تبدیل", icon: trendingDownIcon, describe: () => "نرخ تبدیل دست‌کم ۱۰ واحد کمتر از دورهٔ قبل است" },
  objection_surge: { label: "جهش اعتراض مشتری", icon: trendingDownIcon, describe: (item) => item.title },
  needs_review: { label: "تحلیل نیازمند بازبینی", icon: eyeIcon, describe: () => "نتیجهٔ فروش با اطمینان کافی مشخص نشده است" },
};
const FALLBACK: GroupMeta = { label: "نیازمند بازبینی", icon: eyeIcon, describe: (item) => item.title };

function GroupRow({ group, expanded, onToggle, range }: { group: ActionGroup; expanded: boolean; onToggle: () => void; range: { from: string; to: string } }) {
  const meta = GROUPS[group.type] ?? FALLBACK;
  const urgent = group.severity === "high";
  const first = group.items[0];
  const single = group.count === 1 && first.call_id;
  const head = <>
    <i className="exec-attn__sev" style={{ background: urgent ? "#8a4b3f" : "#b2ac88" }} aria-hidden="true" />
    <span className="exec-attn__icon" style={{ color: urgent ? "#8a4b3f" : "#6f6a4f" }} aria-hidden="true"><Icon icon={meta.icon} className="h-[18px] w-[18px]" /></span>
    <span className="min-w-0 flex-1"><strong className="block truncate text-sm font-bold text-slate-800">{meta.label}</strong><span className="mt-0.5 block truncate text-xs text-slate-500">{meta.describe(first)}</span></span>
    <span className="exec-attn__count">{fmt.int(group.count)}</span>
    <Icon icon={chevronLeftIcon} className={`h-4 w-4 shrink-0 text-slate-400 transition ${expanded ? "-rotate-90" : ""}`} aria-hidden="true" />
  </>;
  if (single) return <li><Link className="exec-attn__row" to={`/calls/${first.call_id}`}>{head}</Link></li>;
  if (group.count === 1 && meta.link) return <li><Link className="exec-attn__row" to={meta.link(range)}>{head}</Link></li>;
  return <li>
    <button type="button" className="exec-attn__row" aria-expanded={expanded} onClick={onToggle}>{head}</button>
    {expanded ? <ul className="exec-attn__items">
      {group.items.slice(0, 6).map((item, index) => <li key={`${item.call_id ?? group.type}-${index}`}>{item.call_id ? <Link to={`/calls/${item.call_id}`}>{meta.describe(item)}</Link> : <span>{meta.describe(item)}</span>}</li>)}
      {meta.link ? <li><Link className="font-bold text-brand-700" to={meta.link(range)}>مشاهدهٔ همه ({fmt.int(group.count)})</Link></li> : group.count > 6 ? <li className="text-slate-500">و {fmt.int(group.count - 6)} مورد دیگر</li> : null}
    </ul> : null}
  </li>;
}

/** Actions grouped by type; urgent first. The expanded group is kept in the URL by the caller. */
export function AttentionPanel({ actions, expanded, onExpand, range }: { actions: KpiDashboard["actions"]; expanded: string; onExpand: (type: string) => void; range: { from: string; to: string } }) {
  const groups = groupActions(actions);
  const urgent = groups.filter((group) => group.severity === "high").reduce((sum, group) => sum + group.count, 0);
  return <DashboardCard title="نیازمند توجه شما" hint={groups.length ? `${fmt.int(actions.length)} مورد${urgent ? ` · ${fmt.int(urgent)} فوری` : ""} · مرتب‌شده بر اساس فوریت` : "مواردی که پیگیری یا تصمیم شما را لازم دارند"}>
    {groups.length ? <ul className="exec-attn">{groups.map((group) => <GroupRow key={group.type} group={group} range={range} expanded={expanded === group.type} onToggle={() => onExpand(expanded === group.type ? "" : group.type)} />)}</ul>
      : <div className="flex items-center gap-3 border border-[color:var(--line)] bg-brand-50 p-4 text-sm text-brand-800"><Icon icon={circleCheckIcon} className="h-6 w-6 shrink-0" aria-hidden="true" /><span>موردی برای رسیدگی فوری باقی نمانده است.</span></div>}
  </DashboardCard>;
}
