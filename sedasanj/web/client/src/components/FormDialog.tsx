import { useEffect, useId, useRef, type ReactNode } from "react";
import "./quick-demo.css";

interface FormDialogProps {
  open: boolean;
  title: string;
  description?: string;
  /** Illustration shown above the title, like the sign-in and quick-demo dialogs. */
  art?: string;
  submitLabel: string;
  busy?: boolean;
  submitDisabled?: boolean;
  error?: string | null;
  /** Wider panel for forms with many fields. */
  wide?: boolean;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
}

/**
 * Modal form in the same shell as the sign-in and quick-demo dialogs (`demo-dialog`): artwork, title, fields as
 * `<label><span>…</span><input/></label>`, and a submit bar pinned to the bottom while the body scrolls.
 */
export default function FormDialog({ open, title, description, art, submitLabel, busy = false, submitDisabled = false, error, wide = false, onSubmit, onClose, children }: FormDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="demo-dialog"
      style={wide ? { width: "min(94vw, 640px)" } : undefined}
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}
      onClick={(event) => { if (event.target === dialogRef.current && !busy) onClose(); }}
    >
      {open ? <>
        <button className="demo-dialog-close" aria-label="بستن" type="button" onClick={onClose} disabled={busy}>×</button>
        {art ? <div className="demo-dialog-artwork" style={{ backgroundImage: `url(${art})` }} aria-hidden="true" /> : null}
        <form className="demo-phone-form" dir="rtl" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
          <h2 id={titleId}>{title}</h2>
          {description ? <p>{description}</p> : null}
          {error ? <p className="demo-error" role="alert">{error}</p> : null}
          {children}
          <div className="demo-dialog-actions">
            <button className="demo-button" disabled={busy || submitDisabled}>{busy ? "لطفاً صبر کنید…" : submitLabel}</button>
          </div>
        </form>
      </> : null}
    </dialog>
  );
}
