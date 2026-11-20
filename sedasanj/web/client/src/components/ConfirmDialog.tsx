import { useEffect, useId, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "انصراف",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [busy, onCancel, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 sm:items-center"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <div
        className="w-full max-w-sm border border-[color:var(--line)] bg-canvas p-5 shadow-2xl"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        dir="rtl"
      >
        <h2 id={titleId} className="text-base font-bold text-[var(--color-primary)]">
          {title}
        </h2>
        <p id={descriptionId} className="mt-3 text-sm leading-7 text-[var(--color-neutral)]">
          {description}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            className="min-h-10 border border-[color:var(--line)] px-4 text-sm font-bold text-[color:var(--ink)] transition hover:bg-[var(--color-canvas)] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`min-h-10 px-4 text-sm font-bold text-white transition disabled:cursor-not-allowed disabled:opacity-50 ${
              destructive ? "bg-[#DC2626] hover:bg-[#B91C1C]" : "bg-[var(--color-primary)] hover:bg-[#3F5D3D]"
            }`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "در حال انجام…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
