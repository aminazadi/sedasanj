import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmt, request } from "../api";
import { useAuth } from "../auth";
import ProcessingIndicator from "../components/ProcessingIndicator";
import type { TokenPair } from "../types";
import { classifyMicrophoneError, isEmbeddedBrowser, microphoneErrorMessage, microphoneSupportIssue, requestMicrophone } from "../lib/microphone.mjs";
import { srcSetFor } from "../lib/imageSources";
import recordingReviewArtwork from "../assets/quick-demo-recording-review.webp";
import "../components/quick-demo.css";

interface RecordingInfo { session_id: string; user_id: string; call_id: string | null; organization_name: string; expires_at: string; completed: boolean; max_duration_seconds: number; prompt_url: string | null }
type Phase = "idle" | "permission" | "prompt" | "beep" | "recording" | "paused" | "review" | "uploading" | "retry" | "done";

function RecorderEqualizer({ active }: { active: boolean }) {
  return <span className={`demo-equalizer${active ? " is-active" : ""}`} aria-hidden="true">{Array.from({ length: 20 }, (_, index) => <i key={index} style={{ "--bar": index } as CSSProperties}/>)}</span>;
}

export default function DemoRecorder() {
  const { session, loading, acceptSession } = useAuth();
  const navigate = useNavigate();
  const [token] = useState(() => window.location.hash.slice(1));
  const [info, setInfo] = useState<RecordingInfo | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [supportIssue, setSupportIssue] = useState<"insecure" | "unsupported" | null>(null);
  const [permissionStuck, setPermissionStuck] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const embedded = useRef(isEmbeddedBrowser(navigator.userAgent));
  const attempt = useRef(0);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const context = useRef<AudioContext | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const recording = useRef<Blob | null>(null);
  const mounted = useRef(true);
  const startedAt = useRef(0);
  const viaQr = useRef(false);
  const timer = useRef<ReturnType<typeof setInterval>>();
  const limitTimer = useRef<ReturnType<typeof setTimeout>>();

  function releaseMicrophone() { stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null; }
  function clearTimers() { clearInterval(timer.current); clearTimeout(limitTimer.current); }
  useEffect(() => {
    mounted.current = true;
    setSupportIssue(microphoneSupportIssue({ isSecureContext: window.isSecureContext, hasGetUserMedia: !!navigator.mediaDevices?.getUserMedia, hasMediaRecorder: typeof MediaRecorder !== "undefined" }));
    if (loading) return;
    if (!token) { setError("لینک تست کامل نیست؛ دوباره QR را اسکن کنید."); return; }
    async function initialize() {
      try {
        const value = await request<RecordingInfo>("/v1/quick-demo/recording/status", { method: "POST", body: { token }, retry: false });
        value.prompt_url = "/quick-demo-instructions.mp3";
        if (!session || session.userId !== value.user_id) {
          const pair = await request<TokenPair>("/v1/quick-demo/recording/login", { method: "POST", body: { token }, retry: false });
          if (!mounted.current) return;
          viaQr.current = true; acceptSession(pair);
        }
        if (!mounted.current) return;
        setInfo(value);
        if (value.completed && value.call_id) navigate(`/calls/${value.call_id}`, { replace: true });
        else if (value.completed) setPhase("done");
      } catch (reason) { if (mounted.current) setError((reason as Error).message); }
    }
    void initialize();
    return () => {
      mounted.current = false; clearTimers(); audio.current?.pause();
      if (recorder.current?.state !== "inactive") recorder.current?.stop();
      releaseMicrophone(); void context.current?.close();
    };
  }, [token, loading, session, acceptSession, navigate]);
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
        if (viaQr.current) setPhase("done");
        else navigate(`/calls/${result.call_id}`, { replace: true });
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
    if (!stream.current || !info || !mounted.current) return;
    try {
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"].find((type) => MediaRecorder.isTypeSupported(type));
      const current = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      current.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      current.onstop = () => {
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
    } catch { releaseMicrophone(); setError("مرورگر قادر به شروع ضبط نیست؛ با Safari یا Chrome به‌روز امتحان کنید."); setPhase("idle"); }
  }
  async function playBeeps() {
    if (!mounted.current || !context.current) return;
    setPhase("beep");
    try {
      await context.current.resume();
      const oscillator = context.current.createOscillator(); const gain = context.current.createGain();
      oscillator.frequency.value = 880; gain.gain.setValueAtTime(0.001, context.current.currentTime); gain.gain.linearRampToValueAtTime(0.12, context.current.currentTime + 0.04); gain.gain.linearRampToValueAtTime(0.001, context.current.currentTime + 1.5); oscillator.connect(gain); gain.connect(context.current.destination);
      await new Promise<void>((resolve) => {
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); resolve(); };
        oscillator.start(); oscillator.stop(context.current!.currentTime + 1.55);
      });
      if (!mounted.current) return;
      startRecording();
    } catch { releaseMicrophone(); setError("پخش بوق انجام نشد؛ دوباره شروع کنید."); setPhase("idle"); }
  }
  async function playPrompt() {
    if (!audio.current) return;
    setError(""); setPhase("prompt");
    await audio.current.play();
  }
  // Browsers only show the microphone prompt for a request made synchronously inside a tap/click, so
  // getUserMedia is the first thing start() does; audio unlock and AudioContext setup follow it.
  async function start(currentInfo = info) {
    if (!currentInfo || supportIssue) return;
    const id = ++attempt.current;
    setError(""); setPermissionStuck(false); setPhase("permission");
    const pending = requestMicrophone(navigator.mediaDevices);
    const stuck = setTimeout(() => { if (attempt.current === id) setPermissionStuck(true); }, 8000);
    try {
      if (context.current && context.current.state !== "closed") void context.current.close();
      const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      context.current = new AudioContextClass(); void context.current.resume().catch(() => undefined);
      const element = audio.current;
      if (element && currentInfo.prompt_url) {
        // Unlock playback inside the tap so the guide can play after the permission prompt (iOS Safari).
        element.muted = true;
        try { await element.play(); element.pause(); } catch { /* handled when the guide starts */ }
        element.muted = false; element.currentTime = 0;
      }
      const granted = await pending;
      if (attempt.current !== id || !mounted.current) { granted.getTracks().forEach((track) => track.stop()); return; }
      stream.current = granted;
      setPermissionStuck(false);
      if (currentInfo.prompt_url) { try { await playPrompt(); } catch { void playBeeps(); } }
      else void playBeeps();
    } catch (reason) {
      if (attempt.current !== id) return;
      releaseMicrophone(); setPhase("idle");
      setError(microphoneErrorMessage(classifyMicrophoneError(reason), { embedded: embedded.current }));
    } finally { clearTimeout(stuck); }
  }
  function cancelPermission() {
    attempt.current += 1; setPermissionStuck(false); setPhase("idle");
  }
  async function copyLink() {
    try { await navigator.clipboard.writeText(window.location.href); setLinkCopied(true); } catch { setError("کپی نشد؛ آدرس صفحه را به‌صورت دستی در Safari یا Chrome باز کنید."); }
  }
  function retryRecording() {
    recording.current = null;
    if (info) void start(info);
  }
  const audioActive = phase === "prompt" || phase === "beep" || phase === "recording";
  return <main className="demo-page demo-recorder-page" dir="rtl"><section className="demo-card">
    {supportIssue && <p className="demo-error" role="alert">{supportIssue === "insecure" ? "ضبط فقط روی اتصال امن HTTPS کار می‌کند؛ لینک را با آدرس https باز کنید." : "این مرورگر از ضبط صدا پشتیبانی نمی‌کند؛ Safari یا Chrome به‌روز را امتحان کنید."}</p>}
    {embedded.current && !supportIssue && phase === "idle" && <div className="demo-note" role="note"><p>به نظر می‌رسد صفحه داخل یک برنامه (مثل پیام‌رسان یا اسکنر) باز شده و ممکن است اجازهٔ میکروفون نمایش داده نشود. بهتر است لینک را در Safari یا Chrome باز کنید.</p><button type="button" className="demo-button demo-retake" onClick={() => void copyLink()}>{linkCopied ? "لینک کپی شد" : "کپی لینک صفحه"}</button></div>}
    {error && <p className="demo-error" role="alert">{error}</p>}
    {info?.prompt_url && phase !== "done" && <audio ref={audio} src={info.prompt_url} preload="auto" playsInline onEnded={() => void playBeeps()} onError={() => { releaseMicrophone(); setPhase("idle"); setError("صدای راهنما بارگذاری نشد؛ اتصال را بررسی و دوباره شروع کنید."); }}/>} 
    {phase === "idle" && info && <><p>برای شروع، دکمهٔ زیر را بزنید و در پنجرهٔ باز‌شده «اجازه دادن» به میکروفون را تأیید کنید.</p><p>راهنما پخش می‌شود؛ پس از یک بوق کشیده پیام خود را بگویید.</p><p className="demo-note">حداکثر {fmt.int(info.max_duration_seconds)} ثانیه</p><button className="demo-audio-control" disabled={!!supportIssue} onClick={() => void start(info)} aria-label="شروع پخش راهنما و ضبط"><RecorderEqualizer active={audioActive}/><strong>شروع پخش و ضبط</strong></button></>}
    {phase === "permission" && <div role="status"><p>در انتظار تأیید شما؛ در پنجرهٔ مرورگر روی «اجازه دادن» برای میکروفون بزنید…</p>{permissionStuck && <p className="demo-note">اگر پنجره‌ای نمایش داده نشد، مرورگر ممکن است میکروفون را برای این سایت مسدود کرده باشد: آیکن قفل کنار آدرس را بزنید، میکروفون را «اجازه» کنید و دوباره شروع کنید. در برنامه‌های داخلی، لینک را در Safari یا Chrome باز کنید.</p>}<button type="button" className="demo-button demo-retake" onClick={cancelPermission}>بازگشت و تلاش دوباره</button></div>}
    {(phase === "prompt" || phase === "beep" || phase === "recording" || phase === "paused") && <div className="demo-audio-stage" role="status">{(phase === "prompt" || phase === "beep") ? <div className="demo-audio-control is-active"><RecorderEqualizer active/><strong>{phase === "prompt" ? "در حال پخش پیام راهنما" : "یک بوق کشیده تا شروع ضبط"}</strong></div> : <><div className="demo-recording-control"><button className="demo-recording-pause" onClick={togglePause} aria-label={phase === "recording" ? "مکث ضبط" : "ادامه ضبط"}>{phase === "recording" ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM15 5h4v14h-4z"/></svg> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 12 7-12 7z"/></svg>}</button><strong>{phase === "recording" ? "در حال ضبط" : "ضبط مکث شده"}</strong></div><div className="demo-recording"><strong role="timer">{fmt.duration(elapsed * 1000)}</strong><button className="demo-button demo-stop" onClick={stop}>پایان ضبط</button></div></>}</div>}
    {phase === "review" && <div className="demo-review" role="group" aria-label="بازبینی صدای ضبط‌شده"><img className="demo-review-artwork" src={recordingReviewArtwork} srcSet={srcSetFor(recordingReviewArtwork)} sizes="(max-width: 528px) calc(100vw - 48px), 480px" width={1000} height={667} alt="پیام صوتی آمادهٔ ارسال است" decoding="async"/><p>ضبط پیام به پایان رسید. می‌توانید ارسال کنید یا دوباره ضبط کنید.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>ارسال پیام صوتی</button><button className="demo-button demo-retake" onClick={retryRecording}>ضبط دوباره</button></div>}
    {phase === "uploading" && <div className="demo-progress" role="status"><ProcessingIndicator size="lg" label="در حال ارسال پیام صوتی"/><p>در حال ارسال پیام صوتی… این صفحه را نبندید.</p></div>}
    {phase === "retry" && <><p>فایل ضبط‌شده در همین صفحه نگه داشته شده است.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>تلاش دوباره برای ارسال</button><button className="demo-button demo-retake" onClick={retryRecording}>ضبط دوباره</button></>}
    {phase === "done" && <div role="status"><p>پیام صوتی ارسال شد و تحلیل آن آغاز می‌شود. ادامهٔ مراحل و نتیجه در همان صفحه‌ای که QR را نشان می‌داد باز می‌شود؛ این صفحه را می‌توانید ببندید.</p>{!viaQr.current && <Link className="demo-button" to={`/quick-demo?step=result&session=${info?.session_id || ""}`}>بازگشت به صفحه تست</Link>}</div>}
  </section></main>;
}
