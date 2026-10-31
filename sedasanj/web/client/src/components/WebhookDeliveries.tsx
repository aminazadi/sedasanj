import { useCallback, useEffect, useState } from "react";
import { request } from "../api";
import type { Page, WebhookDelivery, WebhookTestResult } from "../types";

export default function WebhookDeliveries({ webhookId, onClose }: { webhookId: string; onClose: () => void }) {
  const [items, setItems] = useState<WebhookDelivery[]>([]);
  const [failedOnly, setFailedOnly] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await request<Page<WebhookDelivery>>(`/v1/webhooks/${webhookId}/deliveries?limit=25${failedOnly ? "&failed_only=true" : ""}`);
    setItems(data.items);
  }, [webhookId, failedOnly]);

  useEffect(() => {
    load().catch((error: Error) => setMessage(error.message));
  }, [load]);

  async function redeliver(delivery: WebhookDelivery): Promise<void> {
    setMessage(null);
    try {
      const result = await request<WebhookTestResult>(`/v1/webhooks/deliveries/${delivery.id}/redeliver`, { method: "POST" });
      setMessage(result.ok ? "ارسال مجدد موفق بود." : `ارسال مجدد ناموفق بود: ${result.delivery.error ?? ""}`);
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  return (
    <div className="mb-3 rounded border border-slate-200 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <span className="font-medium">لاگ تحویل</span>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} />
          فقط ناموفق
        </label>
        <button className="btn-ghost text-xs" onClick={onClose}>بستن</button>
      </div>
      {message ? <div className="mb-2 text-sm text-slate-600">{message}</div> : null}
      <table className="table">
        <thead>
          <tr><th>زمان</th><th>رویداد</th><th>تلاش</th><th>وضعیت</th><th>تأخیر</th><th /></tr>
        </thead>
        <tbody>
          {items.map((delivery) => (
            <tr key={delivery.id}>
              <td>{new Date(delivery.created_at).toLocaleString("fa-IR")}</td>
              <td dir="ltr">{delivery.event}</td>
              <td>{delivery.attempt}</td>
              <td dir="ltr">{delivery.error ?? delivery.status_code ?? "—"}</td>
              <td dir="ltr">{delivery.latency_ms != null ? `${delivery.latency_ms} ms` : "—"}</td>
              <td><button className="btn-ghost text-xs" onClick={() => void redeliver(delivery)}>ارسال مجدد</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
