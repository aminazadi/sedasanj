import { useEffect, useMemo, useState, type RefObject } from "react";

const BAR_COUNT = 72;
const EMPTY_WAVEFORM = Array.from({ length: BAR_COUNT }, (_, index) =>
  0.18 + ((index * 17) % 11) / 18,
);

function formatTime(value: number): string {
  const safeValue = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  const minutes = Math.floor(safeValue / 60);
  const seconds = safeValue % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function buildPeaks(buffer: AudioBuffer): number[] {
  const channel = buffer.getChannelData(0);
  const blockSize = Math.max(1, Math.floor(channel.length / BAR_COUNT));
  const peaks = Array.from({ length: BAR_COUNT }, (_, index) => {
    const start = index * blockSize;
    const end = Math.min(channel.length, start + blockSize);
    let peak = 0;
    for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
      peak = Math.max(peak, Math.abs(channel[sampleIndex]));
    }
    return peak;
  });
  const maximum = Math.max(...peaks, 0.01);
  return peaks.map((peak) => Math.max(0.12, peak / maximum));
}

type AudioWaveformPlayerProps = {
  audioRef: RefObject<HTMLAudioElement>;
  src: string;
  onError: () => void;
};

export default function AudioWaveformPlayer({ audioRef, src, onError }: AudioWaveformPlayerProps) {
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [peaks, setPeaks] = useState<number[]>(EMPTY_WAVEFORM);
  const progress = duration > 0 ? Math.min(1, currentTime / duration) : 0;
  const activeBars = Math.round(progress * BAR_COUNT);

  useEffect(() => {
    let cancelled = false;
    const context = new AudioContext();

    void fetch(src)
      .then((response) => response.arrayBuffer())
      .then((data) => context.decodeAudioData(data))
      .then((buffer) => {
        if (!cancelled) setPeaks(buildPeaks(buffer));
      })
      .catch(() => undefined)
      .finally(() => void context.close());

    return () => {
      cancelled = true;
      void context.close();
    };
  }, [src]);

  useEffect(() => {
    void audioRef.current?.play().catch(() => undefined);
  }, [audioRef, src]);

  const waveformLabel = useMemo(
    () => `موقعیت پخش ${formatTime(currentTime)} از ${formatTime(duration)}`,
    [currentTime, duration],
  );

  function togglePlayback() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play().catch(onError);
    else audio.pause();
  }

  function seek(event: React.MouseEvent<HTMLButtonElement>) {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    const target = ratio * audio.duration;
    if (Number.isFinite(target)) audio.currentTime = target;
  }

  function toggleMute() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.muted = !audio.muted;
    setMuted(audio.muted);
  }

  return (
    <div className="border border-[#B2AC88] bg-white/70 px-4 py-3 shadow-sm sm:px-5" dir="rtl">
      <audio
        ref={audioRef}
        src={src}
        className="hidden"
        preload="metadata"
        aria-label="فایل صوتی تماس"
        onDurationChange={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
        onTimeUpdate={(event) => setCurrentTime(Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={onError}
      />
      <div className="flex items-center gap-3 sm:gap-4">
        <button
          type="button"
          className="flex h-11 w-11 shrink-0 items-center justify-center bg-[#4B6E48] text-[#F2F0EF] transition hover:bg-[#3f5f3d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]"
          onClick={togglePlayback}
          aria-label={playing ? "توقف پخش" : "پخش فایل صوتی"}
        >
          {playing ? (
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" /></svg>
          ) : (
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" /></svg>
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <span className="text-xs font-bold text-[#000000]">فایل صوتی تماس</span>
            <span className="shrink-0 text-[11px] tabular-nums text-[#898989]" dir="ltr">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>
          <button
            type="button"
            className="group flex h-10 w-full items-center gap-[2px] overflow-hidden focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]"
            onClick={seek}
            aria-label={waveformLabel}
          >
            {peaks.map((peak, index) => (
              <span
                key={index}
                className={`min-w-[1px] flex-1 transition-colors ${index < activeBars ? "bg-[#4B6E48]" : "bg-[#B2AC88] group-hover:bg-[#898989]"}`}
                style={{ height: `${Math.max(4, Math.round(peak * 36))}px` }}
                aria-hidden="true"
              />
            ))}
          </button>
        </div>

        <button
          type="button"
          className="flex h-9 w-9 shrink-0 items-center justify-center text-[#000000] transition hover:bg-[#B2AC88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#4B6E48]"
          onClick={toggleMute}
          aria-label={muted ? "فعال‌کردن صدا" : "قطع صدا"}
        >
          {muted ? (
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="m17 9 5 5m0-5-5 5" /></svg>
          ) : (
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="M15 9a4 4 0 0 1 0 6m3-9a8 8 0 0 1 0 12" /></svg>
          )}
        </button>
      </div>
    </div>
  );
}
