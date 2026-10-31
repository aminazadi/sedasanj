export const PAGE_SIZES: number[];
export function pageSize(value: unknown, fallback?: number): number;
export function tableOffset(value: unknown): number;
export function withPageSize(params: URLSearchParams, size: number): URLSearchParams;
