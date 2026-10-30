import { useEffect, useState } from "react";
import { fmt } from "../api";
import { startPayment, type GatewayCode } from "../lib/payment";
import PaymentMethodPicker from "./PaymentMethodPicker";

interface Props {
  orderId: string;
  amountToman: number;
  title?: string;
  onClose: () => void;
  onError: (message: string | null) => void;
}

/** Pay an existing unpaid order with one of the enabled gateways. */
export default function OrderPaymentPanel({ orderId, amountToman, title = "پرداخت سفارش", onClose, onError }: Props) {
  const [gateway, setGateway] = useState<GatewayCode | null>(null);
  const [anyMethod, setAnyMethod] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const reset = (event: PageTransitionEvent) => event.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  async function pay() {
    setBusy(true);
    onError(null);
    try {
      await startPayment(orderId, gateway);
    } catch (reason) {
      onError((reason as Error).message);
      setBusy(false);
    }
  }

  return (
    <section className="card order-pay-panel" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-bold">{title}</h2>
        <strong>{fmt.toman(amountToman)}</strong>
      </div>
      <PaymentMethodPicker amountToman={amountToman} value={gateway} onChange={setGateway} onAvailability={setAnyMethod} />
      <div className="flex gap-2">
        <button type="button" className="btn" disabled={busy || !gateway || !anyMethod} onClick={() => void pay()}>
          {busy ? "در حال انتقال به درگاه…" : "پرداخت"}
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onClose}>انصراف</button>
      </div>
    </section>
  );
}
