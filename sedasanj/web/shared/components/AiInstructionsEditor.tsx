import { useEffect, useState } from "react";

export interface AiInstructions {
  coach: string;
  meeting: string;
  max_chars: number;
}

interface AiInstructionsEditorProps {
  load: () => Promise<AiInstructions>;
  save: (changes: Partial<Pick<AiInstructions, "coach" | "meeting">>) => Promise<AiInstructions>;
  /** Who is editing: the text names the place where the organization can see the same fields. */
  audience: "organization" | "staff";
}

const FIELDS = [
  {
    key: "meeting",
    title: "صورت‌جلسهٔ جلسات",
    hint: "لحن، اصطلاحات و ساختار دلخواه صورت‌جلسه. برای جلسه‌های بعدی اعمال می‌شود؛ برای جلسه‌ای که ساخته شده «بازتحلیل» را بزنید.",
  },
  {
    key: "coach",
    title: "مربی ارتباط با مشتری",
    hint: "نکته‌هایی که مربی هنگام بررسی تماس‌های این سازمان باید رعایت یا تأکید کند. از تماس بعدی اعمال می‌شود.",
  },
] as const;

type Field = (typeof FIELDS)[number]["key"];

export default function AiInstructionsEditor({ load, save, audience }: AiInstructionsEditorProps) {
  const [saved, setSaved] = useState<AiInstructions | null>(null);
  const [draft, setDraft] = useState<Record<Field, string>>({ meeting: "", coach: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    load()
      .then((value) => {
        if (!active) return;
        setSaved(value);
        setDraft({ meeting: value.meeting, coach: value.coach });
      })
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, [load]);

  if (!saved) return error ? <p role="alert" className="text-sm text-red-600">{error}</p> : <p className="text-sm text-slate-500">در حال بارگذاری…</p>;

  const changed = FIELDS.filter(({ key }) => draft[key].trim() !== saved[key]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const changes: Partial<Record<Field, string>> = {};
      for (const { key } of changed) changes[key] = draft[key].trim();
      const next = await save(changes);
      setSaved(next);
      setDraft({ meeting: next.meeting, coach: next.coach });
      setNotice("ذخیره شد.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm leading-7 text-slate-600">
        {audience === "organization"
          ? "این متن‌ها به پرامپت پایهٔ سامانه اضافه می‌شوند و جایگزین آن نمی‌شوند؛ قالب خروجی همیشه ثابت می‌ماند."
          : "دستور اختصاصی این سازمان؛ مدیر سازمان هم همین متن را در تنظیمات حساب می‌بیند و می‌تواند ویرایش کند. به پرامپت سراسری اضافه می‌شود و جایگزین آن نمی‌شود."}
      </p>
      {FIELDS.map(({ key, title, hint }) => (
        <section key={key} className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <label className="font-bold text-slate-900" htmlFor={`ai-instructions-${key}`}>{title}</label>
          <p className="text-xs leading-6 text-slate-500">{hint}</p>
          <textarea
            id={`ai-instructions-${key}`}
            className="input min-h-40 resize-y leading-7"
            dir="rtl"
            maxLength={saved.max_chars}
            value={draft[key]}
            onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
          />
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>{draft[key].length.toLocaleString("fa-IR")} از {saved.max_chars.toLocaleString("fa-IR")} نویسه</span>
            <button type="button" className="btn-ghost text-xs" disabled={!draft[key]} onClick={() => setDraft({ ...draft, [key]: "" })}>پاک‌کردن</button>
          </div>
        </section>
      ))}
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
      {notice ? <p role="status" className="text-sm text-emerald-700">{notice}</p> : null}
      <button className="btn" disabled={busy || changed.length === 0}>{busy ? "در حال ذخیره…" : "ذخیره"}</button>
    </form>
  );
}
