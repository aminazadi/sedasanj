/** Quote asset URLs so inlined SVG attributes remain valid inside CSS url(). */
export function cssUrl(source: string): string {
  return `url(${JSON.stringify(source)})`;
}
