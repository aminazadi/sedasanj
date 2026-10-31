import { pageSize, tableOffset, withPageSize } from "./tablePagination.mjs";

type SetParams = (next: URLSearchParams, options?: { replace?: boolean }) => void;

export function tablePreferences(params: URLSearchParams, setParams: SetParams, scope: string): [number, (size: number) => void] {
  const storageKey = `sedasanj:table-page-size:${scope}`;
  let saved = 25;
  try { saved = pageSize(localStorage.getItem(storageKey)); } catch { /* Storage may be unavailable. */ }
  const size = pageSize(params.get("page_size"), saved);
  return [size, (value) => {
    const nextSize = pageSize(value);
    try { localStorage.setItem(storageKey, String(nextSize)); } catch { /* The URL still preserves the selection. */ }
    setParams(withPageSize(params, nextSize));
  }];
}

export function tableOffsetState(params: URLSearchParams, setParams: SetParams, key: string): [number, (offset: number | ((current: number) => number)) => void] {
  const offset = tableOffset(params.get(key));
  return [offset, (value) => {
    const next = new URLSearchParams(params);
    const result = tableOffset(typeof value === "function" ? value(offset) : value);
    if (result) next.set(key, String(result)); else next.delete(key);
    setParams(next);
  }];
}
