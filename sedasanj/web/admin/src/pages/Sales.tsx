import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page } from "../types";

interface Lead { id:string; name:string; organization:string; mobile:string; email:string; message:string; source:string; status:string; internal_notes:string|null; follow_up_at:string|null; created_at:string }

export default function Sales(){
  const limit=25;const [offset,setOffset]=useState(0);const [page,setPage]=useState<Page<Lead>|null>(null);const [error,setError]=useState<string|null>(null);
  async function load(){try{setPage(await request<Page<Lead>>(`/v1/admin/commerce/leads?limit=${limit}&cursor=${offset}`));}catch(reason){setError((reason as Error).message);}}
  useEffect(()=>{void load();},[offset]);
  async function edit(item:Lead, status:string){const notes=window.prompt("یادداشت داخلی",item.internal_notes??"");try{await request(`/v1/admin/commerce/leads/${item.id}`,{method:"PATCH",body:{status,internal_notes:notes}});await load();}catch(reason){setError((reason as Error).message);}}
  return <div className="space-y-4"><div><h1 className="text-2xl font-bold">فروش و سرنخ‌ها</h1><p className="mt-1 text-sm text-slate-500">پیگیری مخاطبان، مسئول رسیدگی و یادداشت داخلی</p></div><ErrorBox message={error}/><div className="card overflow-x-auto">{!page?<Loading/>:page.items.length===0?<Empty/>:<table className="table"><thead><tr><th>مخاطب</th><th>تماس</th><th>پیام</th><th>پیگیری</th><th>وضعیت</th></tr></thead><tbody>{page.items.map(item=><tr key={item.id}><td>{item.name}<small className="block text-slate-400">{item.organization}</small></td><td dir="ltr">{item.mobile}<small className="block">{item.email}</small></td><td className="max-w-md whitespace-normal">{item.message}{item.internal_notes?<small className="mt-1 block text-amber-700">داخلی: {item.internal_notes}</small>:null}</td><td>{item.follow_up_at?fmt.dateTime(item.follow_up_at):'—'}</td><td><select className="input min-w-36" value={item.status} onChange={(event)=>void edit(item,event.target.value)}><option value="new">جدید</option><option value="contacted">تماس گرفته شد</option><option value="qualified">واجد شرایط</option><option value="closed">بسته</option></select></td></tr>)}</tbody></table>}{page?<Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset}/>:null}</div></div>;
}
