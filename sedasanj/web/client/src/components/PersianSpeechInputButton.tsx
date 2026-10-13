import { useEffect, useRef, useState } from "react";

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}

interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function recognitionConstructor(): SpeechRecognitionConstructor | undefined {
  const browserWindow = window as typeof window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor };
  return browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition;
}

export default function PersianSpeechInputButton({ onTranscript, onListeningChange, className = "" }: { onTranscript: (transcript: string) => void; onListeningChange?: (listening: boolean) => void; className?: string }) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const [listening, setListening] = useState(false);
  const supported = typeof window !== "undefined" && Boolean(recognitionConstructor());

  useEffect(() => () => recognitionRef.current?.stop(), []);

  function setActive(next: boolean) {
    setListening(next);
    onListeningChange?.(next);
  }

  function toggleListening() {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      return;
    }
    const Recognition = recognitionConstructor();
    if (!Recognition) return;
    const recognition = new Recognition();
    recognition.lang = "fa-IR";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .filter((result) => result.isFinal)
        .map((result) => result[0].transcript)
        .join(" ")
        .trim();
      if (transcript) onTranscript(transcript);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setActive(false);
    };
    recognition.onerror = () => {
      recognitionRef.current = null;
      setActive(false);
    };
    recognitionRef.current = recognition;
    setActive(true);
    recognition.start();
  }

  const label = !supported ? "تبدیل گفتار فارسی در Chrome پشتیبانی نمی‌شود" : listening ? "توقف تبدیل گفتار فارسی" : "تبدیل گفتار فارسی";
  return <button type="button" className={className} onClick={toggleListening} disabled={!supported} aria-label={label} title={label} aria-pressed={listening}>
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" /></svg>
    {listening ? <span className="flex h-3 items-center gap-0.5" aria-hidden="true"><i className="h-1.5 w-0.5 animate-[pulse_0.6s_ease-in-out_infinite] bg-current" /><i className="h-3 w-0.5 animate-[pulse_0.6s_ease-in-out_0.15s_infinite] bg-current" /><i className="h-2 w-0.5 animate-[pulse_0.6s_ease-in-out_0.3s_infinite] bg-current" /></span> : null}
    <span>{listening ? "در حال شنیدن" : "گفتار"}</span>
  </button>;
}
