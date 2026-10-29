/** Pure state machine behind useResource: previous data is kept while a refetch is in flight. */
export type ResourceStatus = "initial" | "refreshing" | "ready" | "error";

export interface ResourceState<T> {
  data: T | undefined;
  status: ResourceStatus;
  error: string | null;
  /** Id of the request whose result is still accepted. */
  current: number;
}

export type ResourceAction<T> =
  | { type: "start"; id: number; silent: boolean }
  | { type: "success"; id: number; data: T }
  | { type: "failure"; id: number; error: string; silent?: boolean };

export function initialResourceState<T>(): ResourceState<T> {
  return { data: undefined, status: "initial", error: null, current: 0 };
}

export function resourceReducer<T>(state: ResourceState<T>, action: ResourceAction<T>): ResourceState<T> {
  switch (action.type) {
    case "start":
      if (action.silent) return { ...state, current: action.id };
      return {
        ...state,
        current: action.id,
        error: null,
        status: state.data === undefined ? "initial" : "refreshing",
      };
    case "success":
      if (action.id !== state.current) return state;
      return { data: action.data, status: "ready", error: null, current: state.current };
    case "failure":
      if (action.id !== state.current || action.silent) return state;
      return { ...state, status: "error", error: action.error };
  }
}
