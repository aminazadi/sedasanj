import { Icon } from "./SiteIcon";
import { useEffect, useRef, useState } from "react";
import { request } from "../api";
import ProcessingIndicator from "./ProcessingIndicator";

interface StoryQuestion { question: string; video_media_id: string }
interface WhyVideoContent {
  title: string;
  avatar_media_id: string;
  video_media_id: string;
  play_caption: string;
  autoplay: boolean;
  panel_position: "start" | "end";
  questions: StoryQuestion[];
  cta_button_text: string;
  cta_button_link: string;
  cta_phone_label: string;
  cta_phone: string;
}

export interface WhyVideoState {
  content: WhyVideoContent | null;
  open: boolean;
  setOpen: (open: boolean) => void;
}

const mediaUrl = (id: string) => `/v1/help/media/${encodeURIComponent(id)}`;

/** Loads the admin-managed landing video and owns the lightbox open state shared by every trigger on the page. */
export function useWhyVideo(): WhyVideoState {
  const [content, setContent] = useState<WhyVideoContent | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    request<{ content: WhyVideoContent }>("/v1/site/pages/landing_video")
      .then((page) => live && setContent(page.content))
      .catch(() => undefined);
    return () => { live = false; };
  }, []);
  return { content, open, setOpen };
}

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const telHref = (phone: string) => `tel:${phone.replace(/[۰-۹]/g, (digit) => String(PERSIAN_DIGITS.indexOf(digit))).replace(/[^+0-9]/g, "")}`;
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

/** Story panel (bottom corner, modal) that plays the admin-managed intro video, then the answer to each clicked question, and ends with the admin-managed call to action. Renders nothing until a video is uploaded. */
export function WhyVideoDialog({ video }: { video: WhyVideoState }) {
  const { content, open, setOpen } = video;
  const dialog = useRef<HTMLDialogElement>(null);
  const player = useRef<HTMLVideoElement>(null);
  const [asked, setAsked] = useState<number[]>([]);
  const [current, setCurrent] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [ended, setEnded] = useState(false);
  const [paused, setPaused] = useState(false);
  const [time, setTime] = useState({ now: 0, total: 0 });
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
    if (!open) { setAsked([]); setCurrent(null); }
  }, [open, content]);
  if (!content?.video_media_id) return null;
  const questions = content.questions.filter((item) => item.question && item.video_media_id);
  const remaining = questions.map((item, index) => ({ item, index })).filter(({ index }) => !asked.includes(index));
  const sourceId = current === null ? content.video_media_id : questions[current]?.video_media_id ?? content.video_media_id;
  const hasCta = !!(content.cta_button_text && content.cta_button_link) || !!content.cta_phone;
  const showCta = ended && remaining.length === 0 && hasCta;
  const play = (index: number | null) => {
    setCurrent(index);
    if (index !== null) setAsked((list) => list.includes(index) ? list : [...list, index]);
    setLoading(true);
    setEnded(false);
    setPaused(false);
    setTime({ now: 0, total: 0 });
  };
  const toggle = () => {
    const node = player.current;
    if (!node) return;
    if (node.paused) void node.play().catch(() => setPaused(true)); else node.pause();
  };
  return (
    <dialog className="why-story" data-position={content.panel_position} ref={dialog} aria-label={content.title || "چرا صداسنج؟"} onClose={() => setOpen(false)} onClick={(event) => { if (event.target === dialog.current) setOpen(false); }}>
      {open && <>
        <video
          key={sourceId}
          ref={player}
          className="why-story-video"
          src={mediaUrl(sourceId)}
          autoPlay={current !== null || content.autoplay}
          playsInline
          onClick={toggle}
          onLoadedData={() => setLoading(false)}
          onCanPlay={() => setLoading(false)}
          onPlaying={() => { setLoading(false); setPaused(false); }}
          onPause={(event) => setPaused(!event.currentTarget.ended)}
          onTimeUpdate={(event) => { setLoading(false); setTime({ now: event.currentTarget.currentTime, total: event.currentTarget.duration || 0 }); }}
          onEnded={() => setEnded(true)}
        />
        <div className="why-story-top">
          <div className="why-story-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={time.total ? Math.round((time.now / time.total) * 100) : 0}><span style={{ inlineSize: `${time.total ? (time.now / time.total) * 100 : 0}%` }}/></div>
          <span className="why-story-time" dir="ltr">{clock(Math.max(0, time.total - time.now))}</span>
          <button className="why-story-close" type="button" aria-label="بستن" onClick={() => setOpen(false)}><svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19"/></svg></button>
        </div>
        {loading && <div className="why-story-loading"><ProcessingIndicator label="در حال بارگذاری ویدئو"/></div>}
        {paused && !loading && !ended && <button className="why-story-icon why-story-center" type="button" aria-label="ادامه پخش" onClick={toggle}><svg viewBox="0 0 24 24" focusable="false"><path d="M8 5v14l11-7z"/></svg></button>}
        {ended && !showCta && <button className="why-story-icon why-story-center" type="button" aria-label="پخش دوباره" onClick={() => play(current)}><svg viewBox="0 0 24 24" focusable="false"><path d="M12 5V2L7 6l5 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z"/></svg></button>}
        <div className="why-story-bottom">
          {remaining.length > 0 && <div className="why-story-questions">{remaining.map(({ item, index }) => <button key={index} type="button" onClick={() => play(index)}>{item.question}</button>)}</div>}
          {showCta && <div className="why-story-cta">
            {content.cta_button_text && content.cta_button_link && <a className="why-story-cta-main" href={content.cta_button_link} onClick={() => setOpen(false)}>{content.cta_button_text}<Icon name="arrow" size={18}/></a>}
            {content.cta_phone && <a className="why-story-cta-phone" href={telHref(content.cta_phone)}>{content.cta_phone_label && <span>{content.cta_phone_label}</span>}<bdi dir="ltr">{content.cta_phone}</bdi></a>}
            <button type="button" className="why-story-cta-replay" onClick={() => play(current)}><Icon name="refresh" size={18}/>پخش دوباره</button>
          </div>}
          {current !== null && <button className="why-story-home" type="button" aria-label="بازگشت به ویدئوی اصلی" onClick={() => play(null)}><svg viewBox="0 0 24 24" focusable="false"><path d="M12 3 2 12h3v8h5v-6h4v6h5v-8h3z"/></svg></button>}
        </div>
      </>}
    </dialog>
  );
}

/** Large pulsing play button for the hero, with the admin-managed GIF avatar behind the play icon; opens the shared lightbox. Hidden until a video is uploaded. */
export function WhyVideoPlay({ video }: { video: WhyVideoState }) {
  const { content, setOpen } = video;
  const [avatarFailed, setAvatarFailed] = useState(false);
  if (!content?.video_media_id) return null;
  return (
    <button className="why-video-play" type="button" aria-haspopup="dialog" aria-label={`پخش ویدئو: ${content.title || "چرا صداسنج؟"}`} onClick={() => setOpen(true)}>
      <span className="why-video-play-box" aria-hidden="true">{content.avatar_media_id && !avatarFailed && <img src={mediaUrl(content.avatar_media_id)} alt="" onError={() => setAvatarFailed(true)}/>}<svg viewBox="0 0 24 24" focusable="false"><path d="M8 5v14l11-7z"/></svg>{content.play_caption && <span className="why-video-play-caption">{content.play_caption}</span>}</span>
    </button>
  );
}

/** Floating "why Sedasanj?" button: admin-managed label and GIF avatar; opens the shared lightbox. `hidden` hides it while the hero play button is on screen. */
export default function WhyVideoButton({ video, hidden = false }: { video: WhyVideoState; hidden?: boolean }) {
  const { content, setOpen } = video;
  const [avatarFailed, setAvatarFailed] = useState(false);
  if (!content?.video_media_id) return null;
  return (
    <button className="why-video-button" type="button" hidden={hidden} onClick={() => setOpen(true)} aria-haspopup="dialog">
      {content.avatar_media_id && !avatarFailed && <img src={mediaUrl(content.avatar_media_id)} alt="" width="44" height="44" onError={() => setAvatarFailed(true)}/>}
      <span>{content.title || "چرا صداسنج؟"}</span>
    </button>
  );
}
