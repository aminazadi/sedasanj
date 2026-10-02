export default function ApiDocs() {
  return (
    <div className="card overflow-hidden !p-0">
      <div className="border-b border-slate-200 px-4 py-3">
        <h1 className="font-bold">مستندات API مشتری</h1>
        <p className="mt-1 text-sm text-slate-500">قراردادهای احراز هویت، ارسال تماس، گزارش‌ها، وب‌هوک و مدیریت حساب</p>
      </div>
      <iframe title="مستندات API مشتری" src="/v1/docs/customer" className="h-[calc(100vh-11rem)] min-h-[720px] w-full" />
    </div>
  );
}
