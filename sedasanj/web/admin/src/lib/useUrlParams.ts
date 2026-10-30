import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Filters, tabs and paging kept in the query string so a view can be shared and survives reload.
 * A value equal to its default (or empty) is removed from the URL.
 */
export function useUrlParams<T extends Record<string, string>>(defaults: T): [T, (patch: Partial<T>) => void] {
  const [params, setParams] = useSearchParams();
  const keys = Object.keys(defaults);
  const signature = keys.map((key) => params.get(key) ?? "").join("\u0000");
  const values = useMemo(() => {
    const out: Record<string, string> = {};
    for (const key of keys) out[key] = params.get(key) ?? defaults[key];
    return out as T;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);
  const update = useCallback(
    (patch: Partial<T>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(patch)) {
            if (value === undefined || value === "" || value === defaults[key]) next.delete(key);
            else next.set(key, value as string);
          }
          return next;
        },
        { replace: true },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setParams],
  );
  return [values, update];
}

export { toOffset } from "./offset.mjs";
