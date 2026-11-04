import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmt, request } from "../api";
import { useAuth } from "../auth";
import ProcessingIndicator from "../components/ProcessingIndicator";
import type { TokenPair } from "../types";
import { classifyMicrophoneError, isEmbeddedBrowser, microphoneSupportIssue, quickDemoMicrophoneIssues, requestMicrophone, type QuickDemoMicrophoneIssue } from "../lib/microphone.mjs";
import { srcSetFor } from "../lib/imageSources";
import recordingReviewArtwork from "../assets/quick-demo-recording-review.webp";
import "../components/quick-demo.css";

interface RecordingInfo { session_id: string; user_id: string; call_id: string | null; organization_name: string; expires_at: string; completed: boolean; max_duration_seconds: number; prompt_url: string | null }
type Phase = "idle" | "permission" | "prompt" | "beep" | "ready" | "recording" | "paused" | "review" | "uploading" | "retry" | "done";
type MicrophonePolicy = { allowsFeature?: (feature: string) => boolean };

function getMicrophoneSupportIssue() {
  const page = document as Document & { permissionsPolicy?: MicrophonePolicy; featurePolicy?: MicrophonePolicy };
  return microphoneSupportIssue({
    isSecureContext: window.isSecureContext,
    policy: page.permissionsPolicy ?? page.featurePolicy,
    hasGetUserMedia: typeof navigator.mediaDevices?.getUserMedia === "function",
    hasMediaRecorder: typeof MediaRecorder === "function",
  });
}

function MicrophoneNotice({ issue }: { issue: QuickDemoMicrophoneIssue }) {
  const { code, message } = quickDemoMicrophoneIssues[issue];
  return <p className={issue === "pending" ? "demo-note" : "demo-error"} role={issue === "pending" ? undefined : "alert"}>
    {message} <bdi dir="ltr"><code>{code}</code></bdi>
  </p>;
}

function MicrophoneHelp() {
  return <details className="demo-note mt-4 text-right">
    <summary>راهنمای دسترسی میکروفون</summary>
    <p>اگر دکمهٔ شروع را زده‌اید و ضبط شروع نمی‌شود، مجوز سایت، مجوز سیستم یا محیطی که لینک را باز کرده بررسی کنید. اگر قبلاً اجازه داده‌اید، مرورگر می‌تواند مستقیم وارد مرحلهٔ پخش راهنما شود.</p>
    <ol className="list-decimal ps-5">
      <li>در مرورگر داخلی پیام‌رسان یا اسکنر، از منوی برنامه «باز کردن در مرورگر» را بزنید یا همین لینک را در Safari یا Chrome وارد کنید.</li>
      <li>در Safari، از منوی صفحه وارد «تنظیمات وب‌سایت» شوید. در Chrome، از منوی کنار آدرس وارد «مجوزها» یا «تنظیمات سایت» شوید. میکروفون را روی «اجازه» یا «پرسیدن» بگذارید.</li>
      <li>در تنظیمات حریم خصوصی دستگاه، دسترسی میکروفون را برای مرورگر فعال کنید. اگر میکروفون باز نشد، تماس یا برنامهٔ ضبط دیگر را ببندید و ورودی صدا را بررسی کنید.</li>
      <li>به زبانهٔ تست برگردید و «شروع پخش و ضبط» را بزنید. وقتی شمارندهٔ ضبط شروع شد، پیام کوتاهی بگویید و سپس دکمهٔ پایان ضبط را بزنید.</li>
    </ol>
    <p>برای تست‌های بعدی، لینک امن را مستقیم در مرورگر باز کنید و در صورت نیاز فقط به همین سایت مجوز بدهید.</p>
  </details>;
}

function RecorderEqualizer({ active }: { active: boolean }) {
  return <span className={`demo-equalizer${active ? " is-active" : ""}`} aria-hidden="true">{Array.from({ length: 20 }, (_, index) => <i key={index} style={{ "--bar": index } as CSSProperties}/>)}</span>;
}

export default function DemoRecorder() {
  const { session, loading, acceptSession } = useAuth();
  const navigate = useNavigate();
  const [token] = useState(() => window.location.hash.slice(1));
  const [info, setInfo] = useState<(RecordingInfo & { viaQr: boolean }) | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [supportIssue, setSupportIssue] = useState(getMicrophoneSupportIssue);
  const [micIssue, setMicIssue] = useState<QuickDemoMicrophoneIssue | null>(null);
  const [permissionStuck, setPermissionStuck] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [embedded] = useState(() => isEmbeddedBrowser(navigator.userAgent));
  const [framed] = useState(() => window.self !== window.top);
  const attempt = useRef(0);
  const requesting = useRef(false);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const context = useRef<AudioContext | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const cueAudio = useRef<HTMLAudioElement | null>(null);
  const recording = useRef<Blob | null>(null);
  const mounted = useRef(true);
  const startedAt = useRef(0);
  const [device] = useState(() => new URLSearchParams(window.location.search).get("device"));
  const viaQr = info?.viaQr ?? false;
  const timer = useRef<ReturnType<typeof setInterval>>();
  const limitTimer = useRef<ReturnType<typeof setTimeout>>();

  function releaseMicrophone() { stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null; }
  function clearTimers() { clearInterval(timer.current); clearTimeout(limitTimer.current); }
  function stopGuide() {
    if (!cueAudio.current) return;
    cueAudio.current.onended = null;
    cueAudio.current.onerror = null;
    cueAudio.current.pause();
    cueAudio.current = null;
  }
  function closeBeep() {
    const active = context.current;
    context.current = null;
    if (active && active.state !== "closed") void active.close().catch(() => undefined);
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      attempt.current += 1;
      clearTimers();
      stopGuide();
      closeBeep();
      if (recorder.current?.state !== "inactive") recorder.current?.stop();
      releaseMicrophone();
    };
  }, []);
  useEffect(() => {
    if (loading || info) return;
    if (!token) { setError("لینک تست کامل نیست؛ دوباره QR را اسکن کنید."); return; }
    const controller = new AbortController();
    async function initialize() {
      try {
        const value = await request<RecordingInfo>("/v1/quick-demo/recording/status", { method: "POST", body: { token }, retry: false, signal: controller.signal });
        if (controller.signal.aborted) return;
        const sameUser = session?.userId === value.user_id;
        const fromQr = device === "qr" || (device !== "same" && !sameUser);
        setInfo({ ...value, prompt_url: "/quick-demo-instructions.mp3", viaQr: fromQr });
        if (value.completed && value.call_id && !fromQr && sameUser) navigate(`/calls/${value.call_id}`, { replace: true });
        else if (value.completed) setPhase("done");
      } catch (reason) { if (!controller.signal.aborted) setError((reason as Error).message); }
    }
    void initialize();
    return () => controller.abort();
  }, [token, loading, session?.userId, device, info, navigate]);
  useEffect(() => {
    if (phase !== "permission") return;
    const timer = setTimeout(() => setPermissionStuck(true), 8000);
    return () => clearTimeout(timer);
  }, [phase]);
  useEffect(() => {
    if (phase !== "recording") return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase]);

  async function upload(blob: Blob) {
    setPhase("uploading"); setError("");
    const body = new FormData(); body.append("token", token); body.append("file", blob, blob.type.includes("mp4") ? "recording.m4a" : "recording.webm");
    try {
      const result = await request<{ call_id: string }>("/v1/quick-demo/recording/upload", { method: "POST", body, retry: false });
      if (mounted.current) {
        recording.current = null;
        if (session?.userId) sessionStorage.removeItem(`sedasanj.quick-demo.${session.userId}`);
        if (!viaQr && session?.userId === info?.user_id) {
          navigate(`/calls/${result.call_id}`, { replace: true });
          return;
        }
        setPhase("done");
        // A scanner or in-app browser must not spend the one-time login before capture.
        if (session?.userId !== info?.user_id) {
          void request<TokenPair>("/v1/quick-demo/recording/login", { method: "POST", body: { token }, retry: false })
            .then((pair) => {
              if (!mounted.current) return;
              acceptSession(pair);
              if (!viaQr) navigate(`/calls/${result.call_id}`, { replace: true });
            })
            .catch(() => undefined);
        }
      }
    } catch (reason) {
      if (mounted.current) { setError((reason as Error).message); setPhase("retry"); }
    }
  }
  function stop() {
    if (recorder.current?.state === "recording" || recorder.current?.state === "paused") {
      clearTimers(); recorder.current.stop(); setPhase("uploading");
    }
  }
  function togglePause() {
    if (recorder.current?.state === "recording") {
      recorder.current.pause(); clearInterval(timer.current); setPhase("paused");
    } else if (recorder.current?.state === "paused") {
      recorder.current.resume(); startedAt.current = Date.now() - elapsed * 1000;
      timer.current = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 250);
      setPhase("recording");
    }
  }
  function startRecording() {
    if (!stream.current || !info || !mounted.current || recorder.current) return;
    stopGuide();
    closeBeep();
    if (!stream.current.getAudioTracks().some((track) => track.readyState === "live")) {
      releaseMicrophone(); setMicIssue("busy"); setPhase("idle"); return;
    }
    try {
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"].find((type) => MediaRecorder.isTypeSupported?.(type));
      const current = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      current.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      current.onstop = () => {
        recorder.current = null;
        releaseMicrophone(); clearTimers();
        if (!mounted.current) return;
        const blob = new Blob(chunks, { type: current.mimeType || "audio/webm" });
        recording.current = blob;
        if (blob.size) setPhase("review");
        else { setError("صدایی ضبط نشد؛ دوباره تلاش کنید."); setPhase("idle"); }
      };
      current.onerror = () => { setError("ضبط متوقف شد؛ فایل موجود برای ارسال آماده می‌شود."); stop(); };
      recorder.current = current; startedAt.current = Date.now(); setElapsed(0);
      current.start(1000); setPhase("recording");
      timer.current = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 250);
      limitTimer.current = setTimeout(stop, info.max_duration_seconds * 1000);
    } catch { recorder.current = null; releaseMicrophone(); setError("مرورگر قادر به شروع ضبط نیست؛ با Safari یا Chrome به‌روز امتحان کنید."); setPhase("idle"); }
  }
  function prepareBeep() {
    try {
      const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      context.current ??= new AudioContextClass();
      void context.current.resume().catch(() => undefined);
    } catch { closeBeep(); }
  }
  function playBeep() {
    stopGuide();
    const active = context.current;
    if (active?.state !== "running") { setPhase("ready"); return; }
    setPhase("beep");
    try {
      const oscillator = active.createOscillator();
      const gain = active.createGain();
      const now = active.currentTime;
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.12, now + 0.04);
      gain.gain.linearRampToValueAtTime(0.001, now + 1.5);
      oscillator.connect(gain);
      gain.connect(active.destination);
      oscillator.onended = () => { if (context.current === active) startRecording(); };
      oscillator.start();
      oscillator.stop(now + 1.55);
    } catch { closeBeep(); setPhase("ready"); }
  }
  async function playPrompt() {
    const element = audio.current;
    if (!element) { playBeep(); return; }
    cueAudio.current = element;
    setPhase("prompt");
    element.onended = playBeep;
    element.onerror = playBeep;
    try {
      element.currentTime = 0;
      await element.play();
    } catch (reason) {
      if (cueAudio.current !== element) return;
      if (classifyMicrophoneError(reason) === "denied") { stopGuide(); setPhase("ready"); }
      else playBeep();
    }
  }
  async function start() {
    if (!info || requesting.current || stream.current) return;
    const issue = getMicrophoneSupportIssue();
    setSupportIssue(issue);
    if (issue) return;
    const id = ++attempt.current;
    requesting.current = true;
    setError(""); setMicIssue(null); setPermissionStuck(false); setPhase("permission");
    try {
      const granted = await requestMicrophone(navigator.mediaDevices);
      if (attempt.current !== id) { granted.getTracks().forEach((track) => track.stop()); return; }
      stream.current = granted;
    } catch (reason) {
      if (attempt.current !== id) return;
      setMicIssue(getMicrophoneSupportIssue() ?? classifyMicrophoneError(reason));
      setPhase("idle");
      return;
    } finally {
      if (attempt.current === id) requesting.current = false;
    }
    prepareBeep();
    void playPrompt();
  }
  function cancelStart() {
    attempt.current += 1;
    requesting.current = false;
    stopGuide();
    closeBeep();
    releaseMicrophone();
    setPermissionStuck(false); setPhase("idle");
  }
  async function copyLink() {
    try { await navigator.clipboard.writeText(window.location.href); setLinkCopied(true); setCopyFailed(false); }
    catch { setCopyFailed(true); }
  }
  const visibleMicIssue = supportIssue ?? micIssue;
  const showBrowserOptions = (phase === "idle" && (embedded || framed || visibleMicIssue !== null))
    || (phase === "permission" && permissionStuck);
  const audioActive = phase === "prompt" || phase === "beep" || phase === "recording";
  return <main className="demo-page demo-recorder-page" dir="rtl"><section className="demo-card">
    {visibleMicIssue && <MicrophoneNotice issue={visibleMicIssue}/>}
    {showBrowserOptions && token && <div className="demo-note">
      <p>اگر لینک در پیام‌رسان یا اسکنر باز شده، از منوی همان برنامه «باز کردن در مرورگر» را بزنید یا لینک را در Safari یا Chrome وارد کنید.</p>
      {framed && <a className="demo-button demo-retake" href={window.location.href} target="_blank" rel="noreferrer">باز کردن تست در زبانهٔ جداگانه</a>}
      <button type="button" className="demo-button demo-retake" onClick={() => void copyLink()}>{linkCopied ? "لینک کپی شد" : "کپی لینک تست"}</button>
      {copyFailed && <input aria-label="لینک تست برای کپی دستی" className="w-full border p-2" dir="ltr" readOnly value={window.location.href} onFocus={(event) => event.currentTarget.select()}/>}
    </div>}
    {error && <p className="demo-error" role="alert">{error}</p>}
    {info?.prompt_url && phase !== "done" && <audio ref={audio} src={info.prompt_url} preload="auto" playsInline/>}
    {phase === "idle" && !info && !error && <ProcessingIndicator label="در حال آماده‌سازی تست"/>}
    {phase === "idle" && info && !supportIssue && <><p>برای شروع دکمهٔ زیر را بزنید. اگر مرورگر برای میکروفون اجازه خواست، آن را تأیید کنید.</p><p>راهنما پخش می‌شود. پس از بوق، وقتی شمارنده شروع شد، پیام خود را بگویید.</p><p className="demo-note">حداکثر {fmt.int(info.max_duration_seconds)} ثانیه</p><button type="button" className="demo-audio-control" onClick={() => void start()} aria-label="شروع پخش راهنما و ضبط"><RecorderEqualizer active={audioActive}/><strong>شروع پخش و ضبط</strong></button></>}
    {phase === "permission" && <div role="status"><p>در حال دریافت دسترسی میکروفون…</p>{permissionStuck && <MicrophoneNotice issue="pending"/>}<button type="button" className="demo-button demo-retake" onClick={cancelStart}>بازگشت به شروع</button></div>}
    {phase === "ready" && <div role="status">
      <p>میکروفون آماده است. راهنما را پخش کنید یا ضبط را دستی شروع کنید.</p>
      {info?.prompt_url && <button type="button" className="demo-button demo-retake" onClick={() => { prepareBeep(); void playPrompt(); }}>پخش پیام راهنما</button>}
      <button type="button" className="demo-button" onClick={startRecording}>شروع ضبط بدون پخش صدا</button>
      <button type="button" className="demo-button demo-retake" onClick={cancelStart}>بازگشت به شروع</button>
    </div>}
    {(phase === "prompt" || phase === "beep" || phase === "recording" || phase === "paused") && <div className="demo-audio-stage" role="status">{(phase === "prompt" || phase === "beep") ? <div className="demo-audio-control is-active"><RecorderEqualizer active/><strong>{phase === "prompt" ? "در حال پخش پیام راهنما" : "یک بوق کشیده تا شروع ضبط"}</strong></div> : <><div className="demo-recording-control"><button className="demo-recording-pause" onClick={togglePause} aria-label={phase === "recording" ? "مکث ضبط" : "ادامه ضبط"}>{phase === "recording" ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM15 5h4v14h-4z"/></svg> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 12 7-12 7z"/></svg>}</button><strong>{phase === "recording" ? "در حال ضبط" : "ضبط مکث شده"}</strong></div><div className="demo-recording"><strong role="timer">{fmt.duration(elapsed * 1000)}</strong><button className="demo-button demo-stop" onClick={stop}>پایان ضبط</button></div></>}</div>}
    {(phase === "prompt" || phase === "beep") && <button type="button" className="demo-button demo-retake" onClick={startRecording}>عبور از پخش و شروع ضبط</button>}
    {phase === "review" && <div className="demo-review" role="group" aria-label="بازبینی صدای ضبط‌شده"><img className="demo-review-artwork" src={recordingReviewArtwork} srcSet={srcSetFor(recordingReviewArtwork)} sizes="(max-width: 528px) calc(100vw - 48px), 480px" width={1000} height={667} alt="پیام صوتی آمادهٔ ارسال است" decoding="async"/><p>ضبط پیام به پایان رسید. می‌توانید ارسال کنید یا دوباره ضبط کنید.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>ارسال پیام صوتی</button><button className="demo-button demo-retake" onClick={() => void start()}>ضبط دوباره</button></div>}
    {phase === "uploading" && <div className="demo-progress" role="status"><ProcessingIndicator size="lg" label="در حال ارسال پیام صوتی"/><p>در حال ارسال پیام صوتی… این صفحه را نبندید.</p></div>}
    {phase === "retry" && <><p>فایل ضبط‌شده در همین صفحه نگه داشته شده است.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>تلاش دوباره برای ارسال</button><button className="demo-button demo-retake" onClick={() => void start()}>ضبط دوباره</button></>}
    {phase === "done" && <div role="status"><p>پیام صوتی ارسال شد و تحلیل آن آغاز می‌شود. {viaQr ? "نتیجه در صفحه‌ای که QR را نشان می‌داد باز می‌شود." : "نتیجه را در پنل صداسنج دنبال کنید."}</p>{!viaQr && <Link className="demo-button" to={`/quick-demo?step=result&session=${info?.session_id || ""}`}>بازگشت به صفحه تست</Link>}</div>}
    {(phase === "idle" || phase === "permission") && <MicrophoneHelp/>}
  </section></main>;
}
