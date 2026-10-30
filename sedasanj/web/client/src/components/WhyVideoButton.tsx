import { useEffect, useRef, useState } from "react";
import { request } from "../api";

interface WhyVideo { title: string; avatar_media_id: string; video_media_id: string }

const mediaUrl = (id: string) => `/v1/help/media/${encodeURIComponent(id)}`;

/** Floating "why Sedasanj?" button: admin-managed label, GIF avatar and a lightbox video. */
export default function WhyVideoButton() {
  const [content, setContent] = useState<WhyVideo | null>(null);
  const [open, setOpen] = useState(false);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    let live = true;
    request<{ content: WhyVideo }>("/v1/site/pages/landing_video")
      .then((page) => live && setContent(page.content))
      .catch(() => undefined);
    return () => { live = false; };
  }, []);
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);
  if (!content?.video_media_id) return null;
  return <>
    <button className="why-video-button" type="button" onClick={() => setOpen(true)} aria-haspopup="dialog">
      {content.avatar_media_id && !avatarFailed && <img src={mediaUrl(content.avatar_media_id)} alt="" width="44" height="44" onError={() => setAvatarFailed(true)}/>}
      <span>{content.title || "چرا صداسنج؟"}</span>
    </button>
    <dialog className="why-video-dialog" ref={dialog} aria-label={content.title || "چرا صداسنج؟"} onClose={() => setOpen(false)} onClick={(event) => { if (event.target === dialog.current) setOpen(false); }}>
      <button className="why-video-close" type="button" aria-label="بستن" onClick={() => setOpen(false)}>×</button>
      {open && <video src={mediaUrl(content.video_media_id)} controls autoPlay playsInline/>}
    </dialog>
  </>;
}
