interface ToggleSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  className?: string;
  labelClassName?: string;
  dir?: "ltr" | "rtl";
}

export default function ToggleSwitch({
  checked,
  onChange,
  label,
  disabled = false,
  className = "",
  labelClassName = "",
  dir,
}: ToggleSwitchProps) {
  const resolvedDirection = dir ?? "rtl";
  const thumbOffset = checked === (resolvedDirection === "ltr") ? 20 : 0;

  return (
    <div className={`inline-flex items-center gap-2 ${className}`} dir={resolvedDirection}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="shrink-0 cursor-pointer appearance-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          position: "relative",
          display: "inline-block",
          width: "44px",
          height: "24px",
          boxSizing: "border-box",
          flex: "0 0 44px",
          overflow: "hidden",
          verticalAlign: "middle",
          border: "1px solid transparent",
          backgroundColor: checked ? "var(--color-primary)" : "#B2AC88",
          padding: 0,
          transition: "background-color 200ms ease",
        }}
      >
        <span
          aria-hidden="true"
          className="pointer-events-none bg-white shadow-sm"
          style={{
            position: "absolute",
            display: "block",
            left: "1px",
            top: "50%",
            width: "20px",
            height: "20px",
            boxSizing: "border-box",
            transform: `translate(${thumbOffset}px, -50%)`,
            transition: "transform 200ms ease",
          }}
        />
      </button>
      <span className={labelClassName}>{label}</span>
    </div>
  );
}
