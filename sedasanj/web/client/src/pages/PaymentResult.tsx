import { Link, useSearchParams } from "react-router-dom";

export default function PaymentResult() {
  const [params] = useSearchParams();
  const paid = params.get("status") === "paid";
  return <div className="card mx-auto max-w-xl p-10 text-center"><h1 className="text-2xl font-bold">{paid ? "پرداخت با موفقیت ثبت شد" : "پرداخت تکمیل نشد"}</h1><p className="mt-3 text-sm text-slate-500">{paid ? "اشتراک یا اعتبار خریداری‌شده اکنون فعال است." : "می‌توانید از صفحه حساب، سفارش را دوباره پرداخت کنید."}</p><Link className="btn mt-6 inline-flex" to="/account">بازگشت به حساب</Link></div>;
}
