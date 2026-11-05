import { useRef } from "react";
import { fmt } from "../api";
import "./otp-digits.css";

export default function OtpDigits({ value, onChange, autoFocus, label }: { value: string; onChange: (value: string) => void; autoFocus?: boolean; label: string }) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  function enterDigits(index: number, rawValue: string) {
    const digits = fmt.latinDigits(rawValue).replace(/\D/g, "");
    if (!digits) {
      const next = value.split("");
      next[index] = "";
      onChange(next.join(""));
      return;
    }
    const next = value.padEnd(6, " ").split("");
    digits.slice(0, 6 - index).split("").forEach((digit, offset) => { next[index + offset] = digit; });
    onChange(next.join("").replace(/ /g, ""));
    refs.current[Math.min(index + digits.length, 5)]?.focus();
  }
  return <div className="demo-otp-inputs" role="group" aria-label={label} dir="ltr">
    {Array.from({ length: 6 }, (_, index) => <input
      key={index}
      ref={(element) => { refs.current[index] = element; }}
      type="text"
      inputMode="numeric"
      autoComplete={index === 0 ? "one-time-code" : "off"}
      autoFocus={autoFocus && index === 0}
      aria-label={`رقم ${index + 1} از ۶`}
      value={value[index] || ""}
      onChange={(event) => enterDigits(index, event.target.value)}
      onPaste={(event) => { event.preventDefault(); enterDigits(index, event.clipboardData.getData("text")); }}
      onKeyDown={(event) => {
        if (event.key === "Backspace" && !value[index] && index > 0) refs.current[index - 1]?.focus();
        if (event.key === "ArrowLeft" && index < 5) refs.current[index + 1]?.focus();
        if (event.key === "ArrowRight" && index > 0) refs.current[index - 1]?.focus();
      }}
    />)}
  </div>;
}
