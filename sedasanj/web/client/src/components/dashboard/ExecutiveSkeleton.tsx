import { Skeleton, SkeletonChartCard, SkeletonRegion } from "@cbi/web-shared/components/Skeleton";

/** Placeholder with the executive layout's real shape so nothing jumps when data arrives. */
export function ExecutiveSkeleton({ operator }: { operator: boolean }) {
  return <SkeletonRegion>
    <Skeleton className="w-full" style={{ height: "9.5rem" }} />
    <div className="exec-kpis">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="w-full" style={{ height: "9.25rem" }} />)}</div>
    <div className="exec-split">
      <section className="card" aria-hidden="true"><h2 className="mb-4 font-bold">نیازمند توجه شما</h2>{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="mb-2 w-full" style={{ height: "3.25rem" }} />)}</section>
      <section className="card" aria-hidden="true"><h2 className="mb-4 font-bold">پیشرفت اهداف</h2>{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="mb-4 w-full" style={{ height: "2.75rem" }} />)}</section>
    </div>
    <SkeletonChartCard title="روند روزانه" description="کل تماس‌ها و تماس‌های پاسخ‌داده‌شده در هر روز" legend />
    <section className="card" aria-hidden="true"><h2 className="mb-4 font-bold">از تماس تا فروش</h2><Skeleton className="w-full" style={{ height: "6rem" }} /></section>
    <div className="exec-split exec-split--wide">
      <section className="card" aria-hidden="true"><h2 className="mb-4 font-bold">{operator ? "مربی‌گری من" : "تیم"}</h2><Skeleton className="w-full" style={{ height: "16rem" }} /></section>
      <section className="card" aria-hidden="true"><h2 className="mb-4 font-bold">صدای مشتری</h2><Skeleton className="w-full" style={{ height: "16rem" }} /></section>
    </div>
  </SkeletonRegion>;
}
