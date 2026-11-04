import { useCallback, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { jalaseNegarConfig } from "../agentConfig";
import { fmt, request } from "../api";
import { downloadJsonFile } from "../utils/download";
import ConfirmDialog from "./ConfirmDialog";
import { ErrorBox } from "./Widgets";
import type { MeetingDevice, MeetingPairingCode } from "../types";

export default function JalaseNegarPairing() {
  const [pairing, setPairing] = useState<MeetingPairingCode | null>(null);
  const [devices, setDevices] = useState<MeetingDevice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revokeCandidate, setRevokeCandidate] = useState<MeetingDevice | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const loadDevices = useCallback(async () => {
    try {
      const response = await request<{ items: MeetingDevice[] }>("/v1/meetings/devices");
      setDevices(response.items);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, []);

  useEffect(() => { void loadDevices(); }, [loadDevices]);

  useEffect(() => {
    if (!pairing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pairing]);

  async function createCode() {
    setBusy(true);
    setError(null);
    try {
      setPairing(await request<MeetingPairingCode>("/v1/meetings/devices/pairing-codes", { method: "POST", body: {} }));
      setNow(Date.now());
      // The app pairs with this code; refresh the list so a fresh device shows up after it connects.
      void loadDevices();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(device: MeetingDevice) {
    setBusy(true);
    setError(null);
    try {
      await request<void>(`/v1/meetings/devices/${device.id}`, { method: "DELETE" });
      setRevokeCandidate(null);
      await loadDevices();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const expiresInMs = pairing ? Date.parse(pairing.expires_at) - now : 0;
  const expired = pairing !== null && expiresInMs <= 0;
  const config = pairing ? jalaseNegarConfig(pairing.server_url, pairing.pairing_code, pairing.expires_at) : "";
  const minutes = Math.floor(Math.max(0, expiresInMs) / 60000);
  const seconds = Math.floor((Math.max(0, expiresInMs) % 60000) / 1000);
  const activeDevices = devices.filter((device) => !device.revoked_at);

  return (
    <section className="card space-y-5" aria-labelledby="jalase-negar-title">
      <div>
        <h2 id="jalase-negar-title" className="font-bold">اتصال اپ جلسه‌نگار</h2>
        <p className="section-hint">با اپ جلسه‌نگار جلسه‌ها را ضبط کنید تا در صداسنج رونویسی و تحلیل شوند. کد اتصال را در اپ اسکن کنید یا فایل پیکربندی را در آن باز کنید.</p>
      </div>
      <ErrorBox message={error} />
      {pairing && !expired ? (
        <div className="flex flex-wrap items-start gap-6 border border-[color:var(--line)] p-4">
          <div className="border border-[color:var(--line)] bg-white p-3">
            <QRCodeSVG value={config} size={200} level="M" marginSize={2} fgColor="#294c2b" bgColor="#ffffff" title="کد اتصال اپ جلسه‌نگار" />
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <div>
              <p className="text-xs text-slate-500">کد اتصال</p>
              <p className="mt-1 select-all text-2xl font-black tracking-[0.3em]" dir="ltr" data-keep-latin-digits>{pairing.pairing_code}</p>
            </div>
            <p className="border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
              این کد ۱۵ دقیقه معتبر و یک‌بارمصرف است؛ {fmt.int(minutes)}:{String(seconds).padStart(2, "0")} باقی مانده. آن را برای کسی ارسال نکنید.
            </p>
            <button type="button" className="btn-ghost" onClick={() => downloadJsonFile("jalase-negar-config.json", config)}>دانلود فایل پیکربندی</button>
          </div>
        </div>
      ) : null}
      {expired ? <p className="text-sm text-rose-700" role="status">این کد منقضی شد؛ کد جدید بسازید.</p> : null}
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => void createCode()} disabled={busy}>{pairing && !expired ? "ساخت کد جدید" : "ساخت کد اتصال"}</button>
      </div>
      <div className="border-t border-[color:var(--line)] pt-5">
        <h3 className="mb-3 text-sm font-bold">دستگاه‌های متصل</h3>
        {activeDevices.length === 0 ? (
          <p className="text-sm text-slate-500">هنوز دستگاهی متصل نشده است.</p>
        ) : (
          <ul className="divide-y divide-slate-100 border border-[color:var(--line)]">
            {activeDevices.map((device) => (
              <li key={device.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-bold">{device.label || "دستگاه بدون نام"} <span className="font-normal text-slate-400" dir="ltr">{device.token_prefix}…</span></p>
                  <p className="text-xs text-slate-500">آخرین استفاده: {device.last_used_at ? fmt.dateTime(device.last_used_at) : "هنوز استفاده نشده"} · اتصال: {fmt.date(device.created_at)}</p>
                </div>
                <button type="button" className="btn-ghost text-sm text-rose-700" onClick={() => setRevokeCandidate(device)} disabled={busy}>ابطال دسترسی</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <ConfirmDialog
        open={revokeCandidate !== null}
        title="ابطال دسترسی دستگاه"
        description="این دستگاه دیگر نمی‌تواند جلسه ارسال کند. برای اتصال دوباره باید کد اتصال جدید بسازید."
        confirmLabel="ابطال دسترسی"
        destructive
        busy={busy}
        onCancel={() => setRevokeCandidate(null)}
        onConfirm={() => { if (revokeCandidate) void revoke(revokeCandidate); }}
      />
    </section>
  );
}
