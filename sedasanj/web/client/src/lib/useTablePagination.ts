import { useLocation, useSearchParams } from "react-router-dom";
import { tablePreferences, tableOffsetState } from "@cbi/web-shared/lib/useTablePreferences";

export function useTablePageSize(): [number, (size: number) => void] {
  const [params, setParams] = useSearchParams();
  const { pathname } = useLocation();
  return tablePreferences(params, setParams, "client:" + pathname);
}

export function useTableOffset(key = "offset") {
  const [params, setParams] = useSearchParams();
  return tableOffsetState(params, setParams, key);
}
