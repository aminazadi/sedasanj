import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import downloadIcon from "@iconify-icons/lucide/download";
import pencilIcon from "@iconify-icons/lucide/pencil";
import plusIcon from "@iconify-icons/lucide/plus";
import trashIcon from "@iconify-icons/lucide/trash-2";
import uploadIcon from "@iconify-icons/lucide/upload";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { downloadFile, fmt, query, request } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import ConfirmDialog from "../components/ConfirmDialog";
import ExtensionsPanel from "../components/ExtensionsPanel";
import FormDialog from "../components/FormDialog";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import addUserArt from "../assets/add-user.svg";
import importArt from "../assets/assign-operator.svg";
import type { Contact, ContactImportReport, ContactPage, IranGeo } from "../types";

const PAGE_SIZE = 25;

interface ContactForm {
  name: string;
  phone_number: string;
  company: string;
  email: string;
  province: string;
  city: string;
  notes: string;
}

const EMPTY_FORM: ContactForm = { name: "", phone_number: "", company: "", email: "", province: "", city: "", notes: "" };

let geoCache: Promise<IranGeo> | null = null;

/** Provinces and cities come from the API once per page load (about 30 KB). */
function useIranGeo(enabled: boolean): IranGeo | null {
  const [geo, setGeo] = useState<IranGeo | null>(null);
  useEffect(() => {
    if (!enabled) return;
    geoCache ??= request<IranGeo>("/v1/contacts/geo");
    let active = true;
    geoCache.then((value) => active && setGeo(value)).catch(() => { geoCache = null; });
    return () => { active = false; };
  }, [enabled]);
  return geo;
}

function columns(canEdit: boolean): SkeletonColumn[] {
  return [
    { label: "نام", width: "9rem" },
    { label: "شماره تلفن", width: "7rem", dir: "ltr" },
    { label: "شرکت", width: "8rem" },
    { label: "ایمیل", width: "10rem", dir: "ltr" },
    { label: "استان / شهر", width: "8rem" },
    { label: "توضیحات", width: "12rem" },
    ...(canEdit ? [{ label: null, ariaLabel: "عملیات", kind: "button" as const }] : []),
  ];
}

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function ImportReport({ report }: { report: ContactImportReport }) {
  return (
    <div className="space-y-2 text-sm" role="status">
      <p className="font-bold">
        {report.dry_run ? "نتیجهٔ بررسی (هنوز چیزی ذخیره نشده):" : "ایمپورت انجام شد:"}
      </p>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
        <li>ردیف‌های فایل: {fmt.int(report.total_rows)}</li>
        <li>مخاطب جدید: {fmt.int(report.created)}</li>
        <li>به‌روزرسانی‌شده: {fmt.int(report.updated)}</li>
        <li>ردشده (تکراری): {fmt.int(report.skipped)}</li>
        <li>ردیف دارای خطا: {fmt.int(report.error_count)}</li>
      </ul>
      {report.errors.length > 0 ? (
        <div>
          <p className="font-bold text-rose-700">ردیف‌های دارای خطا ثبت نمی‌شوند:</p>
          <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto text-xs">
            {report.errors.map((item) => (
              <li key={`${item.row}-${item.message}`}>
                ردیف {fmt.int(item.row)}: {item.message}
              </li>
            ))}
          </ul>
          {report.error_count > report.errors.length ? (
            <p className="mt-1 text-xs text-slate-500">
              و {fmt.int(report.error_count - report.errors.length)} خطای دیگر؛ پس از اصلاح فایل دوباره بارگذاری کنید.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type ImportStep = "choose" | "preview" | "done";

function ImportDialog({ open, onClose, onImported }: { open: boolean; onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"skip" | "update">("skip");
  const [step, setStep] = useState<ImportStep>("choose");
  const [report, setReport] = useState<ContactImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) return;
    setFile(null);
    setMode("skip");
    setStep("choose");
    setReport(null);
    setError(null);
  }, [open]);

  async function send(dryRun: boolean) {
    if (!file) {
      setError("یک فایل CSV انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("mode", mode);
      body.append("dry_run", String(dryRun));
      const result = await request<ContactImportReport>("/v1/contacts/import", { method: "POST", body });
      setReport(result);
      setStep(dryRun ? "preview" : "done");
      if (!dryRun) onImported();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (step === "done") onClose();
    else if (step === "preview") await send(false);
    else await send(true);
  }

  function reselect() {
    setFile(null);
    setStep("choose");
    setReport(null);
    setError(null);
  }

  const nothingToSave = step === "preview" && report !== null && report.created + report.updated === 0;
  const label = step === "done" ? "بستن" : step === "preview" ? (nothingToSave ? "انتخاب فایل دیگر" : "ثبت در دفترچه تلفن") : "بررسی فایل";

  return (
    <FormDialog
      open={open}
      title="ایمپورت مخاطبان از فایل CSV"
      description="ردیف اول فایل باید عنوان ستون‌ها باشد (نام، شماره تلفن، شرکت، ایمیل، استان، شهر، توضیحات). در اکسل با «CSV UTF-8» ذخیره کنید. ابتدا فایل بررسی می‌شود و چیزی ذخیره نمی‌شود."
      art={importArt}
      submitLabel={label}
      busy={busy}
      error={error}
      onClose={onClose}
      onSubmit={() => void (nothingToSave ? reselect() : submit())}
    >
      {step === "choose" ? (
        <>
          <label>
            <span>فایل CSV (حداکثر ۵ مگابایت و ۲۰٬۰۰۰ ردیف)</span>
            <input className="input" type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
          </label>
          <label>
            <span>اگر شماره قبلاً ثبت شده بود</span>
            <select className="input" value={mode} onChange={(event) => setMode(event.target.value as "skip" | "update")}>
              <option value="skip">نادیده بگیر (اطلاعات فعلی حفظ شود)</option>
              <option value="update">به‌روزرسانی کن (فقط خانه‌های پرشده جایگزین شوند)</option>
            </select>
          </label>
          <button type="button" className="btn-ghost text-sm" onClick={() => void downloadFile("/v1/contacts/template", "contacts-template.csv").catch((err: Error) => setError(err.message))}>
            دریافت فایل نمونه
          </button>
        </>
      ) : report ? (
        <ImportReport report={report} />
      ) : null}
    </FormDialog>
  );
}

export default function Contacts() {
  const { session } = useAuth();
  const canEdit = isOrgAdmin(session?.role);
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search.trim());
  const [pageIndex, setPageIndex] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Contact | null>(null);
  const [form, setForm] = useState<ContactForm>(EMPTY_FORM);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<Contact | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => setPageIndex(0), [debounced]);

  const contacts = useResource<ContactPage>(async (signal) => {
    const response = await request<ContactPage>(`/v1/contacts${query({ q: debounced, offset: pageIndex * PAGE_SIZE, limit: PAGE_SIZE })}`, { signal });
    if (response.total > 0 && pageIndex >= response.pages) {
      setPageIndex(response.pages - 1);
      return new Promise<ContactPage>(() => {});
    }
    return response;
  }, [debounced, pageIndex, reloadKey]);

  const geo = useIranGeo(canEdit);
  const cities = geo?.provinces.find((province) => province.name === form.province)?.cities ?? [];
  const items = contacts.data?.items ?? [];
  const pages = contacts.data?.pages ?? 1;

  function openForm(contact: Contact | null) {
    setEditing(contact);
    setForm(
      contact
        ? { name: contact.name, phone_number: contact.phone_number, company: contact.company ?? "", email: contact.email ?? "", province: contact.province ?? "", city: contact.city ?? "", notes: contact.notes ?? "" }
        : EMPTY_FORM,
    );
    setFormError(null);
    setFormOpen(true);
  }

  async function save() {
    setFormBusy(true);
    setFormError(null);
    try {
      const body = {
        name: form.name,
        phone_number: fmt.latinDigits(form.phone_number),
        company: form.company.trim() || null,
        email: form.email.trim() || null,
        province: form.province || null,
        city: form.province ? form.city || null : null,
        notes: form.notes.trim() || null,
      };
      if (editing) await request<Contact>(`/v1/contacts/${editing.id}`, { method: "PATCH", body });
      else await request<Contact>("/v1/contacts", { method: "POST", body });
      setFormOpen(false);
      setReloadKey((key) => key + 1);
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setFormBusy(false);
    }
  }

  async function remove(contact: Contact) {
    setDeleting(true);
    setActionError(null);
    try {
      await request<void>(`/v1/contacts/${contact.id}`, { method: "DELETE" });
      setDeleteCandidate(null);
      if (items.length === 1 && pageIndex > 0) setPageIndex(pageIndex - 1);
      else setReloadKey((key) => key + 1);
    } catch (err) {
      setActionError((err as Error).message);
      setDeleteCandidate(null);
    } finally {
      setDeleting(false);
    }
  }

  const actions = canEdit ? (
    <div className="flex flex-wrap items-end justify-end gap-2">
      <button type="button" className="btn" onClick={() => openForm(null)}>
        <Icon icon={plusIcon} className="h-4 w-4" aria-hidden="true" /> افزودن مخاطب
      </button>
      <button type="button" className="btn-ghost" onClick={() => setImportOpen(true)}>
        <Icon icon={uploadIcon} className="h-4 w-4" aria-hidden="true" /> ایمپورت CSV
      </button>
      <button
        type="button"
        className="btn-ghost"
        onClick={() => void downloadFile("/v1/contacts/export", "contacts.csv").catch((err: Error) => setActionError(err.message))}
      >
        <Icon icon={downloadIcon} className="h-4 w-4" aria-hidden="true" /> خروجی CSV
      </button>
    </div>
  ) : undefined;

  return (
    <div className="space-y-4">
      <PageHeader
        title="دفترچه تلفن"
        description="عنوان مخاطبان بالای شمارهٔ آن‌ها در فهرست و جزئیات تماس‌ها نمایش داده می‌شود."
        actions={actions}
      />
      <div className="card">
        <label className="block max-w-sm">
          <span className="sr-only">جست‌وجو در دفترچه تلفن</span>
          <input className="input" type="search" placeholder="جست‌وجوی نام، شماره، شرکت، ایمیل، استان یا شهر" value={search} onChange={(event) => setSearch(event.target.value)} />
        </label>
      </div>
      <ErrorBox message={contacts.error ?? actionError} />
      <div className="card">
        {contacts.loading ? (
          <SkeletonTable columns={columns(canEdit)} rows={contacts.data ? Math.min(items.length || 5, PAGE_SIZE) : 8} />
        ) : items.length === 0 ? (
          <Empty>{debounced ? "مخاطبی با این جست‌وجو پیدا نشد." : "دفترچه تلفن خالی است."}</Empty>
        ) : (
          <table className="table" dir="rtl">
            <thead>
              <tr>
                {columns(canEdit).map((column, index) => (
                  <th key={index} aria-label={column.ariaLabel}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((contact) => (
                <tr key={contact.id}>
                  <td className="font-bold">{contact.name}</td>
                  <td dir="ltr">{fmt.digits(contact.phone_number)}</td>
                  <td>{contact.company ?? "—"}</td>
                  <td dir="ltr">{contact.email ?? "—"}</td>
                  <td>{contact.province ? (contact.city && contact.city !== contact.province ? `${contact.province} / ${contact.city}` : contact.province) : "—"}</td>
                  <td className="max-w-xs truncate" title={contact.notes ?? undefined}>{contact.notes ?? "—"}</td>
                  {canEdit ? (
                    <td>
                      <span className="inline-flex gap-1">
                        <button type="button" className="inline-flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-slate-100" aria-label={`ویرایش ${contact.name}`} title="ویرایش" onClick={() => openForm(contact)}>
                          <Icon icon={pencilIcon} className="h-4 w-4" aria-hidden="true" />
                        </button>
                        <button type="button" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-rose-600 transition hover:bg-rose-50" aria-label={`حذف ${contact.name}`} title="حذف" onClick={() => setDeleteCandidate(contact)}>
                          <Icon icon={trashIcon} className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </span>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Pagination
          page={pageIndex + 1}
          hasPrevious={pageIndex > 0}
          hasNext={pageIndex + 1 < pages}
          total={contacts.data?.total}
          loading={contacts.loading}
          onPrevious={() => setPageIndex(pageIndex - 1)}
          onNext={() => setPageIndex(pageIndex + 1)}
        />
      </div>

      <ExtensionsPanel canEdit={canEdit} />

      <FormDialog
        open={formOpen}
        title={editing ? "ویرایش مخاطب" : "افزودن مخاطب"}
        description="شماره به شکل 09121234567، +989121234567 یا با ارقام فارسی پذیرفته می‌شود."
        art={addUserArt}
        submitLabel={editing ? "ذخیره تغییرات" : "افزودن"}
        busy={formBusy}
        error={formError}
        onClose={() => setFormOpen(false)}
        onSubmit={() => void save()}
      >
        <label><span>نام یا عنوان</span><input className="input" value={form.name} maxLength={200} onChange={(event) => setForm({ ...form, name: event.target.value })} required autoFocus /></label>
        <label><span>شماره تلفن</span><input className="input" dir="ltr" inputMode="tel" value={form.phone_number} maxLength={30} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} required /></label>
        <div className="grid gap-[18px] sm:grid-cols-2">
          <label><span>شرکت</span><input className="input" value={form.company} maxLength={200} onChange={(event) => setForm({ ...form, company: event.target.value })} /></label>
          <label><span>ایمیل</span><input className="input" dir="ltr" type="email" value={form.email} maxLength={254} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
        </div>
        <div className="grid gap-[18px] sm:grid-cols-2">
          <label>
            <span>استان</span>
            <select className="input" value={form.province} onChange={(event) => setForm({ ...form, province: event.target.value, city: "" })} disabled={!geo}>
              <option value="">{geo ? "انتخاب استان" : "در حال بارگذاری…"}</option>
              {geo?.provinces.map((province) => <option key={province.name} value={province.name}>{province.name}</option>)}
            </select>
          </label>
          <label>
            <span>شهر</span>
            <select className="input" value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} disabled={!form.province}>
              <option value="">{form.province ? "انتخاب شهر" : "ابتدا استان را انتخاب کنید"}</option>
              {cities.map((city) => <option key={city} value={city}>{city}</option>)}
            </select>
          </label>
        </div>
        <label><span>توضیحات</span><textarea className="input" rows={3} value={form.notes} maxLength={2000} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
      </FormDialog>

      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={() => setReloadKey((key) => key + 1)} />

      <ConfirmDialog
        open={Boolean(deleteCandidate)}
        title="حذف مخاطب"
        description={`«${deleteCandidate?.name ?? ""}» از دفترچه تلفن حذف می‌شود. تماس‌های قبلی تغییری نمی‌کنند و فقط عنوان کنار شماره نمایش داده نمی‌شود.`}
        confirmLabel="حذف مخاطب"
        destructive
        busy={deleting}
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => { if (deleteCandidate) void remove(deleteCandidate); }}
      />
    </div>
  );
}
