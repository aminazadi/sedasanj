import { lazy, Suspense, type ComponentProps } from "react";
import type RichEditor from "./RichDocumentEditor";

const RichDocumentEditor = lazy(() => import("./RichDocumentEditor"));

export default function DocumentEditor(props: ComponentProps<typeof RichEditor>) {
  return <Suspense fallback={<p className="py-8 text-center text-sm" role="status">در حال آماده‌سازی ویرایشگر…</p>}>
    <RichDocumentEditor {...props} />
  </Suspense>;
}
