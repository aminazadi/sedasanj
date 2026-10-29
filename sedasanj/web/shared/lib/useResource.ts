import { useCallback, useEffect, useReducer, useRef } from "react";
import { initialResourceState, resourceReducer, type ResourceState } from "./resourceState";

export type { ResourceStatus } from "./resourceState";

export interface Resource<T> {
  /** Last successful result; kept while a new one is loading. */
  data: T | undefined;
  /** "initial" until the first result, then "refreshing" while refetching. */
  status: ResourceState<T>["status"];
  error: string | null;
  /** True whenever skeletons should show: first load or a non-silent refetch. */
  loading: boolean;
  /** Refetches; a silent reload (polling) does not change status. */
  reload: (options?: { silent?: boolean }) => void;
}

/**
 * Loads data and keeps the previous result while refetching. A newer request aborts the older one and
 * a stale response is dropped, so filters and pages cannot overwrite each other.
 * `fetcher` may be inline; the request restarts only when `deps` change.
 */
export function useResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[]): Resource<T> {
  const [state, dispatch] = useReducer(resourceReducer<T>, undefined, initialResourceState<T>);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const counter = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback((silent: boolean) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const id = ++counter.current;
    dispatch({ type: "start", id, silent });
    fetcherRef.current(abort.signal).then(
      (data) => dispatch({ type: "success", id, data }),
      (reason: unknown) => {
        if (abort.signal.aborted || (reason instanceof DOMException && reason.name === "AbortError")) return;
        dispatch({ type: "failure", id, silent, error: reason instanceof Error ? reason.message : String(reason) });
      },
    );
  }, []);

  useEffect(() => {
    run(false);
    return () => controller.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reload = useCallback((options?: { silent?: boolean }) => run(Boolean(options?.silent)), [run]);

  return {
    data: state.data,
    status: state.status,
    error: state.error,
    loading: state.status === "initial" || state.status === "refreshing",
    reload,
  };
}
