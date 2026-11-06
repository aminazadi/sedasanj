import logoSource from "../assets/sedasanj-refined-master.svg?raw";
import fontUrl from "../fonts/Vazirmatn-Variable.woff2?url";

let exportFont: Promise<string> | undefined;
function inlineFont(): Promise<string> {
  exportFont ??= fetch(fontUrl).then(response => {
    if (!response.ok) throw new Error("Font unavailable");
    return response.blob();
  }).then(blob => new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Font unavailable"));
    reader.readAsDataURL(blob);
  })).catch(error => { exportFont = undefined; throw error; });
  return exportFont;
}

const SITE_URL = "sedasanj.ir";
const LOGO_COLOR = "#4B6E48";
let footerLogo: Promise<{ data: string; ratio: number }> | undefined;
// Rasterise the vector logo, cropped to its own bounds, for the per-page PDF footer.
function logoImage(): Promise<{ data: string; ratio: number }> {
  footerLogo ??= (async () => {
    const path = logoSource.match(/<path[^>]+\sd="([^"]+)"/)?.[1];
    const numbers = path?.match(/-?\d+(?:\.\d+)?/g)?.map(Number);
    if (!path || !numbers || numbers.length < 2) throw new Error("Logo unavailable");
    const xs = numbers.filter((_, i) => i % 2 === 0), ys = numbers.filter((_, i) => i % 2 === 1);
    const [x, y] = [Math.min(...xs), Math.min(...ys)];
    const [w, h] = [Math.max(...xs) - x, Math.max(...ys) - y];
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${w} ${h}" width="${w * 4}" height="${h * 4}"><path d="${path}" fill="${LOGO_COLOR}" fill-rule="evenodd"/></svg>`;
    const image = new Image();
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = w * 4; canvas.height = h * 4;
    canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height);
    return { data: canvas.toDataURL("image/png"), ratio: w / h };
  })().catch(error => { footerLogo = undefined; throw error; });
  return footerLogo;
}

type FooterPdf = {
  internal: { getNumberOfPages(): number; pageSize: { getWidth(): number; getHeight(): number } };
  setPage(page: number): unknown;
  setFont(name: string): unknown; setFontSize(size: number): unknown;
  setTextColor(r: number, g: number, b: number): unknown;
  getTextWidth(text: string): number;
  addImage(data: string, format: string, x: number, y: number, w: number, h: number): unknown;
  text(text: string, x: number, y: number): unknown;
};

function addPageFooters(pdf: FooterPdf, logo: { data: string; ratio: number }) {
  const logoHeight = 4, gap = 2;
  const logoWidth = logoHeight * logo.ratio;
  pdf.setFont("helvetica"); pdf.setFontSize(8); pdf.setTextColor(91, 101, 90);
  const total = logoWidth + gap + pdf.getTextWidth(SITE_URL);
  const left = (pdf.internal.pageSize.getWidth() - total) / 2;
  const baseline = pdf.internal.pageSize.getHeight() - 8;
  for (let page = 1; page <= pdf.internal.getNumberOfPages(); page += 1) {
    pdf.setPage(page);
    pdf.addImage(logo.data, "PNG", left, baseline - logoHeight + 0.6, logoWidth, logoHeight);
    pdf.text(SITE_URL, left + logoWidth + gap, baseline);
  }
}

export async function renderDocumentPdf(element: HTMLElement): Promise<Blob> {
  const [{ default: html2pdf }, { toCanvas }, fontData, logo] = await Promise.all([
    import("html2pdf.js"), import("html-to-image"), inlineFont(), logoImage(),
  ]);
  const source = element.cloneNode(true) as HTMLElement;
  for (const heading of source.querySelectorAll(".markdown-message h1, .markdown-message h2, .markdown-message h3")) {
    const next = heading.nextElementSibling;
    if (!next || !next.matches("p,ul,ol")) continue;
    const group = document.createElement("div");
    group.className = "document-section-start";
    group.style.display = "flow-root";
    heading.before(group);
    group.append(heading, next);
  }
  const worker = html2pdf().set({
    margin: [12, 12, 18, 12], image: { type: "jpeg", quality: 0.98 },
    jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
    ...{ pagebreak: { mode: ["css", "legacy"], avoid: ["p", "li", "tr", ".statistics-chart", ".document-section-start", "h1", "h2", "h3"] } },
  }).from(source);
  let overlay: HTMLElement | undefined;
  try {
    // Reuse the pagination engine, then let the browser shape RTL text and paint SVG charts.
    await worker.toContainer();
    overlay = await worker.get("overlay");
    const container: HTMLElement = await worker.get("container");
    const canvas = await toCanvas(container, {
      pixelRatio: container.scrollHeight < 7500 ? 2 : Math.min(1, 16000 / Math.max(1, container.scrollHeight)),
      skipAutoScale: true,
      backgroundColor: "#ffffff",
      fontEmbedCSS: `@font-face{font-family:Vazirmatn;src:url('${fontData}');font-weight:100 900;font-style:normal}`,
      style: { position: "static", margin: "0", left: "0", right: "auto" },
    });
    if (!canvas.width || !canvas.height) throw new Error("Document capture failed");
    const withFooter = worker.from(canvas).toPdf().get("pdf", (pdf: FooterPdf) => { addPageFooters(pdf, logo); });
    return await (withFooter as unknown as typeof worker).outputPdf("blob") as Blob;
  } finally {
    overlay?.remove();
  }
}
