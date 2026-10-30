/** A page offset from a URL parameter: a positive integer, anything else is the first page. */
export function toOffset(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}
