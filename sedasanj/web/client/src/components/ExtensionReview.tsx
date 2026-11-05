import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { query, request } from "../api";
import { ErrorBox } from "./Widgets";

interface RepairItem {
  call_id: string;
  started_at: string;
  direction: string | null;
  proposed_direction: string | null;
  operators: string[];
  proposed_operators: string[];
  status: "review" | "unchanged" | "ambiguous";
  token: string | null;
}

interface RepairPage {
  items: RepairItem[];
  has_more: boolean;
  operator_names: Record<string, string>;
}

const LIMIT = 25;
const directions: Record<string, string> = { inbound: "ورودی", outbound: "خروجی", internal: "داخلی" };

function dateBoundary(value: string) {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export default function ExtensionReview() {
  const [params, setParams] = useSearchParams();
  const open = params.get("review") === "1";
  const offset = Math.max(0, Number.parseInt(params.get("offset") ?? "", 10) || 0);
  const from = params.get("from") ?? "";
  const before = params.get("before") ?? "";
  const source = useResource<{ host_uuid: string | null }>(
    (signal) => request("/v1/extensions/source", { signal }), [],
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const page = useResource<RepairPage | null>(
    (signal) => open
      ? request(`/v1/extensions/review${query({ offset, limit: LIMIT, started_from: dateBoundary(from), started_before: dateBoundary(before) })}`, { signal })
      : Promise.resolve(null),
    [open, offset, from, before],
  );

  function navigate(nextOpen: boolean, nextOffset = 0) {
    const next = new URLSearchParams(params);
    if (nextOpen) next.set("review", "1");
    else next.delete("review");
    if (nextOffset) next.set("offset", String(nextOffset));
    else next.delete("offset");
    setParams(next);
  }

  function setDate(key: "from" | "before", value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  }

  function names(ids: string[]) {
    return ids.map((id) => page.data?.operator_names[id] ?? id).join("، ") || "بدون اپراتور";
  }

  async function resetSource(host: string) {
    if (!window.confirm("اتصال فعلی آزاد شود؟ سپس از سانترال جدید همگام‌سازی کنید.")) return;
    setBusy(true);
    setError(null);
    try {
      await request(`/v1/extensions/source/${host}`, { method: "DELETE" });
      source.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "آزادسازی اتصال انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function applyRepairs() {
    const items = page.data?.items.flatMap(({ call_id, token }) => token ? [{ call_id, token }] : []) ?? [];
    if (!items.length || !window.confirm("اصلاح‌های قابل اعمال در این صفحه تأیید شوند؟ دسترسی و گزارش تماس‌ها ممکن است تغییر کند.")) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await request<{ applied: string[]; skipped: string[] }>("/v1/extensions/review", {
        method: "POST",
        body: { items },
      });
      setMessage(`${result.applied.length.toLocaleString("fa-IR")} اصلاح ثبت شد؛ ${result.skipped.length.toLocaleString("fa-IR")} مورد نیاز به بازبینی دوباره دارد.`);
      page.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "اصلاح ثبت نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-bold">اتصال سانترال و بازبینی تماس‌ها</h2>
      <ErrorBox message={error ?? source.error ?? page.error} />
      {message ? <p role="status">{message}</p> : null}
      {source.data?.host_uuid ? (
        <button type="button" className="btn" disabled={busy} onClick={() => void resetSource(source.data!.host_uuid!)}>
          آزادسازی اتصال سانترال
        </button>
      ) : null}
      <button type="button" className="btn" onClick={() => navigate(!open)} aria-expanded={open}>
        {open ? "بستن بازبینی" : "بازبینی سوابق تماس"}
      </button>
      {open ? (
        <div className="flex flex-wrap gap-2">
          <label>از تاریخ <input type="date" className="input" value={from} onChange={(event) => setDate("from", event.target.value)} /></label>
          <label>پیش از تاریخ <input type="date" className="input" value={before} onChange={(event) => setDate("before", event.target.value)} /></label>
        </div>
      ) : null}
      {open && page.data ? (
        <>
          <ul className="space-y-2">
            {page.data.items.map((item) => (
              <li key={item.call_id}>
                <Link to={`/calls/${item.call_id}`}>{new Date(item.started_at).toLocaleString("fa-IR")}</Link>
                {" · "}{directions[item.direction ?? ""] ?? "نامشخص"}
                {item.status === "review" ? (
                  <> ← {directions[item.proposed_direction ?? ""] ?? "نامشخص"} · دسترسی {names(item.operators)} ← {names(item.proposed_operators)}</>
                ) : item.status === "ambiguous" ? " · شواهد ناکافی برای اصلاح" : " · بدون تغییر"}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" disabled={busy || offset === 0} onClick={() => navigate(true, offset - LIMIT)}>صفحه قبل</button>
            <button type="button" className="btn" disabled={busy || !page.data.has_more} onClick={() => navigate(true, offset + LIMIT)}>صفحه بعد</button>
            <button type="button" className="btn" disabled={busy || page.loading || !page.data.items.some((item) => item.token)} onClick={() => void applyRepairs()}>
              تأیید اصلاح‌های این صفحه
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
