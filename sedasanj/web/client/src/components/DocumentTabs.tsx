export default function DocumentTabs<T extends string>({ value, options, onChange, label, align = "center", variant = "solid" }: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  label: string;
  align?: "start" | "center";
  /** "sub" is a quiet underline switch for a second level of tabs. */
  variant?: "solid" | "sub";
}) {
  if (variant === "sub") return <div className="sub-tabs" role="tablist" aria-label={label}>
    {options.map((option, index) => <button
      key={option.value} type="button" role="tab" aria-selected={value === option.value}
      tabIndex={value === option.value ? 0 : -1}
      onClick={() => onChange(option.value)}
      onKeyDown={(event) => {
        let next = index;
        if (event.key === "ArrowLeft") next = (index + 1) % options.length;
        else if (event.key === "ArrowRight") next = (index + options.length - 1) % options.length;
        else return;
        event.preventDefault();
        const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]");
        onChange(options[next].value);
        buttons?.[next].focus();
      }}
    >{option.label}</button>)}
  </div>;
  return <div className={`${align === "start" ? "me-auto" : "mx-auto"} mb-6 flex w-fit max-w-full overflow-x-auto border border-[var(--color-accent)] bg-canvas p-1`} role="tablist" aria-label={label}>
    {options.map((option, index) => <button
      key={option.value} type="button" role="tab" aria-selected={value === option.value}
      tabIndex={value === option.value ? 0 : -1}
      className={`min-h-10 shrink-0 whitespace-nowrap px-4 text-sm font-bold transition ${value === option.value ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-primary)] hover:bg-[var(--color-canvas)]"}`}
      onClick={() => onChange(option.value)}
      onKeyDown={(event) => {
        let next = index;
        if (event.key === "ArrowLeft") next = (index + 1) % options.length;
        else if (event.key === "ArrowRight") next = (index + options.length - 1) % options.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = options.length - 1;
        else return;
        event.preventDefault();
        const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]");
        onChange(options[next].value);
        buttons?.[next].focus();
      }}
    >{option.label}</button>)}
  </div>;
}
