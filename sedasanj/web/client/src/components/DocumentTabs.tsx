export default function DocumentTabs<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  label: string;
}) {
  return <div className="mx-auto mb-6 flex w-fit max-w-full overflow-x-auto border border-[#B2AC88] bg-white p-1" role="tablist" aria-label={label}>
    {options.map((option, index) => <button
      key={option.value} type="button" role="tab" aria-selected={value === option.value}
      tabIndex={value === option.value ? 0 : -1}
      className={`min-h-10 shrink-0 whitespace-nowrap px-4 text-sm font-bold transition ${value === option.value ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`}
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
