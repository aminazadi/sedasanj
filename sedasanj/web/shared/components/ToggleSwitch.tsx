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
        className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer appearance-none items-center overflow-hidden border border-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          backgroundColor: checked ? "var(--color-primary)" : "#B2AC88",
          padding: "1px",
          transition: "background-color 200ms ease",
        }}
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-0.5 top-1/2 block h-5 w-5 shrink-0 bg-white shadow-sm"
          style={{
            transform: `translate(${thumbOffset}px, -50%)`,
            transition: "transform 200ms ease",
          }}
        />
      </button>
      <span className={labelClassName}>{label}</span>
    </div>
  );
}
