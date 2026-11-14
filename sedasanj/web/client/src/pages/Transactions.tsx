import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import { useTablePageSize } from "../lib/useTablePagination";
import type { LedgerEntry, Page } from "../types";

const LEDGER_LABELS: Record<string, string> = {
  reservation: "رزرو",
  settlement: "تسویه",
  release: "آزادسازی",
  topup: "شارژ",
  adjustment: "اصلاح",
  subscription_credit: "هدیه اشتراک",
  credit_purchase: "خرید اعتبار",
  expiration: "انقضای اعتبار",
  refund: "بازپرداخت",
};

/** Credit ledger on its own page, so the account page stays about plan and top-up. */
export default function Transactions() {
  const [limit] = useTablePageSize();
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("ledger")) || 0);
  const [ledger, setLedger] = useState<LedgerEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    request<Page<LedgerEntry>>(`/v1/billing/ledger?limit=${limit}&offset=${offset}`)
      .then((data) => {
        setLedger(data.items);
        setTotal(data.total);
      })
      .catch((reason) => setError((reason as Error).message));
  }, [limit, offset]);

  function go(value: number) {
    const next = new URLSearchParams(params);
    if (value > 0) next.set("ledger", String(value));
    else next.delete("ledger");
    setParams(next, { replace: true });
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="تراکنش‌ها"
        description="تاریخچهٔ تغییرهای اعتبار سازمان"
        actions={<Link className="btn-ghost" to="/account">بازگشت به اعتبار و اشتراک</Link>}
      />
      <ErrorBox message={error} />
      {ledger === null && !error ? <Loading /> : null}
      {ledger ? (
        <div className="card">
          {ledger.length === 0 ? (
            <Empty />
          ) : (
            <table className="table">
              <thead>
                <tr><th>زمان</th><th>نوع</th><th>ثانیه</th><th>تومان</th></tr>
              </thead>
              <tbody>
                {ledger.map((entry) => (
                  <tr key={entry.id}>
                    <td>{fmt.dateTime(entry.created_at)}</td>
                    <td>{LEDGER_LABELS[entry.kind] ?? entry.kind}</td>
                    <td dir="ltr">{fmt.int(entry.seconds_delta)}</td>
                    <td dir="ltr">{fmt.int(entry.toman_delta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Pagination page={Math.floor(offset / limit) + 1} hasPrevious={offset > 0} hasNext={offset + limit < total} total={total} onPrevious={() => go(Math.max(0, offset - limit))} onNext={() => go(offset + limit)} />
        </div>
      ) : null}
    </div>
  );
}
