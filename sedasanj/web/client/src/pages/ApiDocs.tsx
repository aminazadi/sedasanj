import { PageHeader } from "../components/PageHeader";

export default function ApiDocs() {
  return (
    <div className="space-y-4">
      <PageHeader title="مستندات API مشتری" description="قراردادهای احراز هویت، ارسال تماس، گزارش‌ها، وب‌هوک و مدیریت حساب" />
      <section className="card overflow-hidden !p-0">
        <iframe title="مستندات API مشتری" src="/v1/docs/customer" className="h-[calc(100vh-14rem)] min-h-[720px] w-full" />
      </section>
    </div>
  );
}
