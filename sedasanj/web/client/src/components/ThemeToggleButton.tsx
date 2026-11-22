import { Icon, type IconifyIcon } from "@iconify/react";
import monitorIcon from "@iconify-icons/lucide/monitor";
import moonIcon from "@iconify-icons/lucide/moon";
import sunIcon from "@iconify-icons/lucide/sun";
import { useTheme, type ThemeMode } from "@cbi/web-shared/lib/theme";

const THEME_OPTIONS: { value: ThemeMode; icon: IconifyIcon; label: string }[] = [
  { value: "light", icon: sunIcon, label: "روشن" },
  { value: "dark", icon: moonIcon, label: "تاریک" },
  { value: "system", icon: monitorIcon, label: "سیستم" },
];

/** Single icon button that cycles روشن/تاریک/سیستم, for pages outside the panel sidebar (public site header, auth pages). */
export default function ThemeToggleButton({ className = "" }: { className?: string }) {
  const { mode, setMode } = useTheme();
  const index = THEME_OPTIONS.findIndex((option) => option.value === mode);
  const current = THEME_OPTIONS[index] ?? THEME_OPTIONS[0];
  const next = THEME_OPTIONS[(index + 1) % THEME_OPTIONS.length];
  return (
    <button
      type="button"
      className={className}
      aria-label={`ظاهر برنامه: ${current.label} (برای تغییر کلیک کنید)`}
      title={`ظاهر برنامه: ${current.label}`}
      onClick={(event) => setMode(next.value, { x: event.clientX, y: event.clientY })}
    >
      <Icon icon={current.icon} width={18} height={18} aria-hidden="true"/>
    </button>
  );
}
