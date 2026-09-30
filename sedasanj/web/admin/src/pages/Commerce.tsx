import { useCallback, useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page } from "../types";

type Tab = "orders" | "payments" | "invoices" | "refunds";
interface Order { id:string; tenant_id:string; tenant_name?:string; number:string; kind:string; status:string; amount_toman:number; customer_name:string; customer_mobile:string; created_at:string; paid_at:string|null }
interface Payment { id:string; order_id:string; tenant_id:string; status:string; gateway:string; amount_rial:number; authority_hint:string|null; ref_id:string|null; created_at:string }
interface Invoice { id:string; order_id:string; tenant_id:string; number:string; amount_toman:number; issued_at:string }
interface Refund { id:string; order_id:string; tenant_id:string; amount_toman:number; status:string; method:string; reason:string; created_at:string }

const STATUS: Record<string,string> = { draft:"پیش‌نویس", pending_payment:"در انتظار پرداخت", paid:"پرداخت‌شده", canceled:"لغوشده", refunded:"بازپرداخت‌شده", partially_refunded:"بازپرداخت جزئی", redirected:"هدایت‌شده", verified:"تأییدشده", pending_verification:"نیازمند بررسی", failed:"ناموفق", completed:"تکمیل‌شده" };

export default function Commerce() {
  const limit = 25;
  const [tab,setTab] = useState<Tab>("orders");
  const [offset,setOffset] = useState(0);
  const [data,setData] = useState<Page<Order|Payment|Invoice|Refund>|null>(null);
  const [detail,setDetail] = useState<unknown>(null);
  const [error,setError] = useState<string|null>(null);
  const load = useCallback(async () => { try { setData(await request<Page<Order|Payment|Invoice|Refund>>(`/v1/admin/commerce/${tab}?limit=${limit}&cursor=${offset}`)); setDetail(null); } catch(reason){setError((reason as Error).message);} },[offset,tab]);
  useEffect(()=>{void load();},[load]);

  async function reconcile(id:string){try{await request(`/v1/admin/commerce/payments/${id}/reconcile`,{method:"POST"});await load();}catch(reason){setError((reason as Error).message);}}
  async function cancel(order:Order){const reason=window.prompt("دلیل ابطال سفارش را وارد کنید");if(!reason)return;try{await request(`/v1/admin/commerce/orders/${order.id}/cancel`,{method:"POST",body:{reason}});await load();}catch(value){setError((value as Error).message);}}
  async function refund(order:Order){const raw=window.prompt("مبلغ بازپرداخت به تومان",String(order.amount_toman));if(!raw)return;const reason=window.prompt("دلیل بازپرداخت را وارد کنید");if(!reason)return;const external=window.prompt("شناسه بازپرداخت خارجی/دستی");if(!external)return;try{await request(`/v1/admin/commerce/orders/${order.id}/refunds`,{method:"POST",body:{amount_toman:Number(fmt.latinDigits(raw)),method:"manual",reason,external_reference:external},headers:{"Idempotency-Key":crypto.randomUUID()}});await load();}catch(value){setError((value as Error).message);}}

  return <div className="space-y-4"><div><h1 className="text-2xl font-bold">سفارش‌ها و پرداخت‌ها</h1><p className="mt-1 text-sm text-slate-500">پیگیری سفارش، تلاش پرداخت، فاکتور و بازپرداخت</p></div><ErrorBox message={error}/>
    <div className="flex flex-wrap gap-2">{([['orders','سفارش‌ها'],['payments','پرداخت‌ها'],['invoices','فاکتورها'],['refunds','بازپرداخت‌ها']] as const).map(([value,label])=><button key={value} className={tab===value?'btn':'btn-ghost'} onClick={()=>{setTab(value);setOffset(0);}}>{label}</button>)}</div>
    <div className="card overflow-x-auto">{!data?<Loading/>:data.items.length===0?<Empty/>:tab==='orders'?<table className="table"><thead><tr><th>شماره</th><th>سازمان</th><th>نوع</th><th>وضعیت</th><th>مبلغ</th><th>زمان</th><th>عملیات</th></tr></thead><tbody>{(data.items as Order[]).map(item=><tr key={item.id}><td dir="ltr">{item.number}</td><td>{item.tenant_name??item.tenant_id}</td><td>{item.kind}</td><td>{STATUS[item.status]??item.status}</td><td>{fmt.toman(item.amount_toman)}</td><td>{fmt.dateTime(item.created_at)}</td><td className="space-x-2 space-x-reverse"><button className="btn-ghost text-xs" onClick={async()=>setDetail(await request(`/v1/admin/commerce/orders/${item.id}`))}>جزئیات</button>{['draft','pending_payment'].includes(item.status)?<button className="btn-ghost text-xs text-rose-700" onClick={()=>void cancel(item)}>ابطال</button>:null}{['paid','partially_refunded'].includes(item.status)?<button className="btn-ghost text-xs" onClick={()=>void refund(item)}>بازپرداخت</button>:null}</td></tr>)}</tbody></table>:tab==='payments'?<table className="table"><thead><tr><th>سفارش</th><th>درگاه</th><th>وضعیت</th><th>مبلغ</th><th>شناسه</th><th>زمان</th><th/></tr></thead><tbody>{(data.items as Payment[]).map(item=><tr key={item.id}><td dir="ltr">{item.order_id}</td><td>{item.gateway}</td><td>{STATUS[item.status]??item.status}</td><td>{fmt.toman(item.amount_rial/10)}</td><td dir="ltr">{item.ref_id??item.authority_hint??'—'}</td><td>{fmt.dateTime(item.created_at)}</td><td>{item.status==='pending_verification'?<button className="btn-ghost text-xs" onClick={()=>void reconcile(item.id)}>تطبیق امن</button>:null}</td></tr>)}</tbody></table>:tab==='invoices'?<table className="table"><thead><tr><th>شماره</th><th>سفارش</th><th>مبلغ</th><th>صدور</th></tr></thead><tbody>{(data.items as Invoice[]).map(item=><tr key={item.id}><td dir="ltr">{item.number}</td><td dir="ltr">{item.order_id}</td><td>{fmt.toman(item.amount_toman)}</td><td>{fmt.dateTime(item.issued_at)}</td></tr>)}</tbody></table>:<table className="table"><thead><tr><th>سفارش</th><th>روش</th><th>وضعیت</th><th>مبلغ</th><th>دلیل</th><th>زمان</th></tr></thead><tbody>{(data.items as Refund[]).map(item=><tr key={item.id}><td dir="ltr">{item.order_id}</td><td>{item.method==='reverse'?'ریورس درگاه':'دستی'}</td><td>{STATUS[item.status]??item.status}</td><td>{fmt.toman(item.amount_toman)}</td><td>{item.reason}</td><td>{fmt.dateTime(item.created_at)}</td></tr>)}</tbody></table>}</div>
    {data?<Pagination offset={offset} limit={limit} total={data.total} onChange={setOffset}/>:null}
    {detail?<section className="card"><div className="mb-3 flex justify-between"><h2 className="font-bold">جزئیات سفارش</h2><button className="btn-ghost" onClick={()=>setDetail(null)}>بستن</button></div><pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs" dir="ltr">{JSON.stringify(detail,null,2)}</pre></section>:null}
  </div>;
}
