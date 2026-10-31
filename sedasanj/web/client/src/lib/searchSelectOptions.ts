export interface SearchSelectOption {
  value: string;
  label: string;
  /** Extra text matched by local search but not displayed. */
  keywords?: string;
}

function normalize(text: string): string {
  return text.toLocaleLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک");
}

export function searchSelectOptions(options: SearchSelectOption[], term: string, {
  remote = false, emptyLabel = "", allowEmpty = true,
}: { remote?: boolean; emptyLabel?: string; allowEmpty?: boolean } = {}): SearchSelectOption[] {
  const needle = normalize(term.trim());
  const matches = needle && !remote
    ? options.filter((option) => normalize(`${option.label} ${option.keywords ?? ""}`).includes(needle))
    : options;
  return allowEmpty && emptyLabel && !needle ? [{ value: "", label: emptyLabel }, ...matches] : matches;
}
