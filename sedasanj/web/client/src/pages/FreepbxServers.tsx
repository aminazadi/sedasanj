import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SeverityBadge } from "@cbi/web-shared/components/ReleaseTimeline";
import { fmt } from "../api";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import { loadModuleFleet, type ModuleFleet, type ModuleInstallation } from "../moduleUpdates";

const UPDATE_STATUS: Record<NonNullable<ModuleInstallation["last_update_status"]>, { label: string; className: string }> = {
  started: { label: "در حال به‌روزرسانی", className: "badge-info" },
  succeeded: { label: "به‌روزرسانی موفق", className: "badge-success" },
  failed: { label: "به‌روزرسانی ناموفق", className: "badge-danger" },
  rolled_back: { label: "بازگردانی به نسخهٔ قبل", className: "badge-warning" },
};

export default function FreepbxServers() {
  const [fleet, setFleet] = useState<ModuleFleet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadModuleFleet(true)
      .then(setFleet)
      .catch((err) => setError((err as Error).message));
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader title="سرورهای FreePBX" description="وضعیت سرورهای متصل و نسخهٔ ماژول نصب‌شده روی هر کدام" />
      <ErrorBox message={error} />
      {fleet?.latest ? (
        <section className="card flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm text-slate-500">آخرین نسخهٔ منتشرشده</div>
            <div className="mt-1 flex items-center gap-2">
              <span className="font-mono text-xl font-extrabold text-slate-900" dir="ltr" data-keep-latin-digits>v{fleet.latest.version}</span>
              <SeverityBadge severity={fleet.latest.severity} />
            </div>
            <div className="mt-1 text-sm text-slate-700">{fleet.latest.title}</div>
          </div>
          <Link className="btn-ghost" to={`/module-changelog#v${fleet.latest.version}`}>مشاهدهٔ تغییرات</Link>
        </section>
      ) : null}

      <section className="card">
        <h2 className="font-bold">سرورهای FreePBX سازمان</h2>
        <p className="section-hint mb-4">
          هر سرور با باز شدن صفحهٔ «Seda Sanj» در پنل FreePBX این‌جا ثبت می‌شود. برای به‌روزرسانی، همان صفحه را در FreePBX باز کنید و دکمهٔ «به‌روزرسانی» را بزنید.
        </p>
        {!fleet && !error ? (
          <Loading />
        ) : !fleet?.items.length ? (
          <Empty>هنوز سروری گزارش نشده است.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>سرور</th>
                  <th>نسخهٔ ماژول</th>
                  <th>FreePBX</th>
                  <th>سرویس آپلود</th>
                  <th>آخرین ارتباط</th>
                  <th>آخرین به‌روزرسانی</th>
                </tr>
              </thead>
              <tbody>
                {fleet.items.map((item) => {
                  const update = item.last_update_status ? UPDATE_STATUS[item.last_update_status] : null;
                  return (
                    <tr key={item.id}>
                      <td className="font-mono text-xs" dir="ltr" data-keep-latin-digits>{item.hostname ?? item.host_uuid.slice(0, 8)}</td>
                      <td>
                        <span className="font-mono" dir="ltr" data-keep-latin-digits>v{item.module_version}</span>{" "}
                        {item.update_available ? (
                          <span className="badge badge-warning">نسخهٔ <span dir="ltr" data-keep-latin-digits>v{item.latest_version}</span> آماده است</span>
                        ) : (
                          <span className="badge badge-success">به‌روز</span>
                        )}
                      </td>
                      <td dir="ltr" className="text-xs" data-keep-latin-digits>{item.freepbx_version ?? "—"}</td>
                      <td>{item.service_status === "running" ? "فعال" : item.service_status === "stopped" ? "متوقف" : "—"}</td>
                      <td>{fmt.dateTime(item.last_seen_at)}</td>
                      <td>
                        {update ? <span className={`badge ${update.className}`}>{update.label}</span> : "—"}
                        {item.last_update_error ? (
                          <div className="mt-1 max-w-xs truncate text-xs text-rose-700" title={item.last_update_error}>{item.last_update_error}</div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
