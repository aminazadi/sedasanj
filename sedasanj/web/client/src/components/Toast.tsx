import { useEffect } from "react";
import { createPortal } from "react-dom";

export default function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 6000);
    return () => window.clearTimeout(timer);
  }, [message, onClose]);

  return createPortal(
    <div className="fixed inset-x-4 top-6 z-[100] mx-auto flex w-fit max-w-[calc(100%-2rem)] items-center gap-4 border border-[#B2AC88] bg-[#F2F0EF] px-4 py-3 text-sm text-[#365033] shadow-lg" dir="rtl">
      <span role="alert">{message}</span>
      <button type="button" onClick={onClose} aria-label="بستن پیام" className="shrink-0 px-1 text-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-current">×</button>
    </div>,
    document.body,
  );
}
