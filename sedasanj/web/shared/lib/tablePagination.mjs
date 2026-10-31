export const PAGE_SIZES = [10, 25, 50, 100, 200];

export function pageSize(value, fallback = 25) {
  const parsed = Number(value);
  return PAGE_SIZES.includes(parsed) ? parsed : fallback;
}

export function tableOffset(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export function withPageSize(params, size) {
  const next = new URLSearchParams(params);
  next.set("page_size", String(pageSize(size)));
  for (const key of [...next.keys()]) {
    if (key === "page" || key === "offset" || key.endsWith("_offset") || key.endsWith("_page") || ["ledger", "orders"].includes(key)) next.delete(key);
  }
  return next;
}
