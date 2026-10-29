import { useCallback, useEffect, useRef, useState } from "react";
import { fmt, request, uploadWithProgress } from "../api";
import { formatBytes } from "../sanitize";
import type { HelpMedia } from "../types";
import { Empty, ErrorBox, Loading } from "./Widgets";

/** Builds the HTML inserted into an article for a media item. */
export function mediaHtml(media: HelpMedia): string {
  const alt = media.alt.replace(/"/g, "&quot;");
  if (media.kind === "video") {
    return `<p><video src="${media.url}" controls preload="metadata"></video></p>`;
  }
  return `<figure><img src="${media.url}" alt="${alt}">${alt ? `<figcaption>${alt}</figcaption>` : ""}</figure>`;
}

/** Media URLs are public, so a plain <img> works for thumbnails. */
function Thumb({ media }: { media: HelpMedia }) {
  if (media.kind === "video") {
    return (
      <div className="flex h-24 items-center justify-center rounded bg-slate-100 text-xs text-slate-500" dir="ltr">
        {media.content_type}
      </div>
    );
  }
  return <img src={media.url} alt={media.alt} className="h-24 w-full rounded object-cover" loading="lazy" />;
}

export default function HelpMediaLibrary({ onPick }: { onPick?: (media: HelpMedia) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<HelpMedia[] | null>(null);
  const [alt, setAlt] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setItems(await request<HelpMedia[]>("/v1/admin/help/media"));
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function upload(file: File) {
    setError(null);
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    form.append("alt", alt);
    try {
      const media = await uploadWithProgress<HelpMedia>("/v1/admin/help/media", form, setProgress);
      setAlt("");
      await reload();
      if (onPick) onPick(media);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
    }
  }

  async function remove(media: HelpMedia) {
    if (!window.confirm(`«${media.filename}» حذف شود؟`)) return;
    try {
      await request(`/v1/admin/help/media/${media.id}`, { method: "DELETE" });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div className="card space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">متن جایگزین (برای دسترس‌پذیری و زیرنویس)</label>
            <input className="input" value={alt} maxLength={300} onChange={(e) => setAlt(e.target.value)} />
          </div>
          <div className="flex items-end">
            <button type="button" className="btn" disabled={progress !== null} onClick={() => input.current?.click()}>
              {progress === null ? "آپلود تصویر یا ویدئو" : `در حال آپلود ${fmt.digits(String(Math.round(progress * 100)))}٪`}
            </button>
            <input
              ref={input}
              type="file"
              className="hidden"
              accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void upload(file);
              }}
            />
          </div>
        </div>
        <p className="text-xs text-slate-500">
          تصویر: PNG، JPEG، WebP، GIF تا ۸ مگابایت. ویدئو: MP4 یا WebM تا ۱۲۰ مگابایت. نوع فایل از محتوای آن تشخیص داده می‌شود.
        </p>
      </div>
      {items === null ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>هنوز فایلی آپلود نشده است.</Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((media) => (
            <div key={media.id} className="card space-y-2 p-3">
              <Thumb media={media} />
              <div className="truncate text-xs text-slate-600" dir="ltr" title={media.filename}>
                {media.filename}
              </div>
              <div className="text-xs text-slate-400">{formatBytes(media.size_bytes)}</div>
              <div className="flex gap-2">
                {onPick ? (
                  <button type="button" className="btn btn-sm" onClick={() => onPick(media)}>
                    درج
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => void navigator.clipboard?.writeText(`${window.location.origin}${media.url}`)}
                  >
                    کپی نشانی
                  </button>
                )}
                <button type="button" className="btn btn-ghost btn-sm text-rose-600" onClick={() => void remove(media)}>
                  حذف
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
