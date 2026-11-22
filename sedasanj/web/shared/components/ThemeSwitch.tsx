import { useTheme } from "../lib/theme";
import type { ThemeMode } from "../lib/theme";

const OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "روشن" },
  { value: "dark", label: "تاریک" },
  { value: "system", label: "سیستم" },
];

/** Three-way روشن/تاریک/سیستم appearance switch, for a settings/profile page. */
export default function ThemeSwitch({ className = "" }: { className?: string }) {
  const { mode, setMode } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="ظاهر برنامه"
      className={`inline-flex divide-x divide-[color:var(--line-strong)] border border-[color:var(--line-strong)] ${className}`}
    >
      {OPTIONS.map((option) => {
        const active = option.value === mode;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={(e) => setMode(option.value, { x: e.clientX, y: e.clientY })}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              active ? "bg-selected text-primary-dark" : "text-ink-soft hover:bg-canvas"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
