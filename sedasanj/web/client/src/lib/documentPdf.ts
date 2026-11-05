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

export async function renderDocumentPdf(element: HTMLElement): Promise<Blob> {
  const [{ default: html2pdf }, { toCanvas }, fontData] = await Promise.all([
    import("html2pdf.js"), import("html-to-image"), inlineFont(),
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
    margin: [12, 12], image: { type: "jpeg", quality: 0.98 },
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
    return await worker.from(canvas).outputPdf("blob") as Blob;
  } finally {
    overlay?.remove();
  }
}
