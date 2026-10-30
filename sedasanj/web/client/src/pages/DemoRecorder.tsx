import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmt, request } from "../api";
import { useAuth } from "../auth";
import type { TokenPair } from "../types";
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
  const [supported, setSupported] = useState(true);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const context = useRef<AudioContext | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const recording = useRef<Blob | null>(null);
  const mounted = useRef(true);
  const startedAt = useRef(0);
  const autoStarted = useRef(false);
  const timer = useRef<ReturnType<typeof setInterval>>();
  const limitTimer = useRef<ReturnType<typeof setTimeout>>();

  function releaseMicrophone() { stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null; }
  function clearTimers() { clearInterval(timer.current); clearTimeout(limitTimer.current); }
  useEffect(() => {
    mounted.current = true;
    setSupported(window.isSecureContext && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined");
    if (loading) return;
    if (!token) { setError("لینک تست کامل نیست؛ دوباره QR را اسکن کنید."); return; }
    async function initialize() {
      try {
        const value = await request<RecordingInfo>("/v1/quick-demo/recording/status", { method: "POST", body: { token }, retry: false });
        value.prompt_url = "/quick-demo-instructions.mp3";
        if (!session || session.userId !== value.user_id) {
          const pair = await request<TokenPair>("/v1/quick-demo/recording/login", { method: "POST", body: { token }, retry: false });
          if (!mounted.current) return;
          acceptSession(pair);
        }
        if (!mounted.current) return;
        setInfo(value);
        if (value.completed && value.call_id) navigate(`/calls/${value.call_id}`, { replace: true });
        else if (value.completed) setPhase("done");
        else if (!autoStarted.current) setInfo(value);
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
    if (info && !info.completed && !autoStarted.current) {
      autoStarted.current = true;
      void start(info, true);
    }
  }, [info]);
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
        navigate(`/calls/${result.call_id}`, { replace: true });
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
  async function start(currentInfo = info, automatic = false) {
    if (!currentInfo || !supported) return;
    setError(""); setPhase("permission");
    try {
      if (context.current && context.current.state !== "closed") await context.current.close();
      context.current = new AudioContext(); await context.current.resume();
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      if (!mounted.current) { releaseMicrophone(); return; }
      if (currentInfo.prompt_url) { audio.current!.currentTime = 0; await playPrompt(); }
      else void playBeeps();
    } catch (reason) {
      releaseMicrophone(); setPhase("idle");
      if (automatic && (reason as DOMException).name === "NotAllowedError") setError("مرورگر اجازهٔ شروع خودکار را نداد؛ برای ادامه دکمهٔ شروع را بزنید.");
      else setError((reason as DOMException).name === "NotAllowedError" ? "دسترسی میکروفون را از تنظیمات مرورگر فعال کنید و دوباره شروع کنید." : "میکروفون در دسترس نیست؛ مرورگر یا دستگاه دیگری را امتحان کنید.");
    }
  }
  function retryRecording() {
    recording.current = null;
    if (info) void start(info);
  }
  const audioActive = phase === "prompt" || phase === "beep" || phase === "recording";
  return <main className="demo-page demo-recorder-page" dir="rtl"><section className="demo-card">
    {!supported && <p className="demo-error" role="alert">برای ضبط، لینک را با Safari یا Chrome به‌روز و اتصال HTTPS باز کنید.</p>}
    {error && <p className="demo-error" role="alert">{error}</p>}
    {info?.prompt_url && phase !== "done" && <audio ref={audio} src={info.prompt_url} preload="auto" playsInline onEnded={() => void playBeeps()} onError={() => { releaseMicrophone(); setPhase("idle"); setError("صدای راهنما بارگذاری نشد؛ اتصال را بررسی و دوباره شروع کنید."); }}/>} 
    {phase === "idle" && info && <><p>راهنما پخش می‌شود؛ پس از یک بوق کشیده پیام خود را بگویید.</p><p className="demo-note">حداکثر {fmt.int(info.max_duration_seconds)} ثانیه</p><button className="demo-audio-control" disabled={!supported} onClick={() => void start(info)} aria-label="شروع پخش راهنما و ضبط"><RecorderEqualizer active={audioActive}/><strong>شروع پخش و ضبط</strong></button></>}
    {phase === "permission" && <p role="status">در انتظار دسترسی به میکروفون…</p>}
    {(phase === "prompt" || phase === "beep" || phase === "recording" || phase === "paused") && <div className="demo-audio-stage" role="status">{(phase === "prompt" || phase === "beep") ? <div className="demo-audio-control is-active"><RecorderEqualizer active/><strong>{phase === "prompt" ? "در حال پخش پیام راهنما" : "یک بوق کشیده تا شروع ضبط"}</strong></div> : <><div className="demo-recording-control"><button className="demo-recording-pause" onClick={togglePause} aria-label={phase === "recording" ? "مکث ضبط" : "ادامه ضبط"}>{phase === "recording" ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM15 5h4v14h-4z"/></svg> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 12 7-12 7z"/></svg>}</button><strong>{phase === "recording" ? "در حال ضبط" : "ضبط مکث شده"}</strong></div><div className="demo-recording"><strong role="timer">{fmt.duration(elapsed * 1000)}</strong><button className="demo-button demo-stop" onClick={stop}>پایان ضبط</button></div></>}</div>}
    {phase === "review" && <div className="demo-review" role="group" aria-label="بازبینی صدای ضبط‌شده"><img className="demo-review-artwork" src={recordingReviewArtwork} srcSet={srcSetFor(recordingReviewArtwork)} sizes="(max-width: 528px) calc(100vw - 48px), 480px" width={1000} height={667} alt="پیام صوتی آمادهٔ ارسال است" decoding="async"/><p>ضبط پیام به پایان رسید. می‌توانید ارسال کنید یا دوباره ضبط کنید.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>ارسال پیام صوتی</button><button className="demo-button demo-retake" onClick={retryRecording}>ضبط دوباره</button></div>}
    {phase === "uploading" && <div className="demo-progress" role="status"><span className="demo-spinner"/><p>در حال ارسال پیام صوتی… این صفحه را نبندید.</p></div>}
    {phase === "retry" && <><p>فایل ضبط‌شده در همین صفحه نگه داشته شده است.</p><button className="demo-button" onClick={() => recording.current && void upload(recording.current)}>تلاش دوباره برای ارسال</button><button className="demo-button demo-retake" onClick={retryRecording}>ضبط دوباره</button></>}
    {phase === "done" && <div role="status"><p>پیام صوتی در فهرست تماس‌های سازمان قرار گرفت و تحلیل آن آغاز می‌شود. نتیجه در صفحه‌ای که تست را شروع کردید نمایش داده می‌شود.</p><Link className="demo-button" to={`/quick-demo?step=result&session=${info?.session_id || ""}`}>بازگشت به صفحه تست</Link></div>}
  </section></main>;
}
