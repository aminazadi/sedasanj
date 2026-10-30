import { request } from "../api";
import zarinpalLogo from "../assets/payments/zarinpal.svg";
import zibalLogo from "../assets/payments/zibal.svg";
import samanLogo from "../assets/payments/saman.svg";
import behpardakhtLogo from "../assets/payments/behpardakht.svg";

export type GatewayCode = "zarinpal" | "zibal" | "saman" | "behpardakht";

export interface PaymentMethod {
  code: GatewayCode;
  name: string;
  description: string;
  min_toman: number;
  max_toman: number | null;
  available: boolean;
  sandbox: boolean;
}

export interface RedirectSpec {
  method: "GET" | "POST";
  url: string;
  fields: Record<string, string>;
}

export const GATEWAY_LOGOS: Record<GatewayCode, string> = {
  zarinpal: zarinpalLogo,
  zibal: zibalLogo,
  saman: samanLogo,
  behpardakht: behpardakhtLogo,
};

/** Sends the browser to the bank: a plain redirect, or an auto-submitted POST form (SEP, Mellat). */
export function submitRedirect(spec: RedirectSpec): void {
  if (spec.method === "GET") {
    window.location.assign(spec.url);
    return;
  }
  const form = document.createElement("form");
  form.method = "POST";
  form.action = spec.url;
  form.style.display = "none";
  for (const [name, value] of Object.entries(spec.fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
}

export async function startPayment(orderId: string, gateway?: GatewayCode | null): Promise<void> {
  const payment = await request<{ redirect: RedirectSpec }>(`/v1/orders/${orderId}/pay`, {
    method: "POST",
    body: gateway ? { gateway } : {},
  });
  submitRedirect(payment.redirect);
}
