import type { ReactNode } from "react";

type FileKind = "sheet" | "csv" | "pdf" | "json" | "markdown" | "text" | "word" | "slides" | "archive" | "image" | "audio" | "other";

interface KindStyle { color: string; label: string; glyph: ReactNode }

const grid = <path d="M7 11h10M7 14h10M7 17h10M11 9v10" />;

const kinds: Record<FileKind, KindStyle> = {
  sheet: { color: "#1D6F42", label: "XLSX", glyph: grid },
  csv: { color: "#4B6E48", label: "CSV", glyph: grid },
  pdf: { color: "#C0392B", label: "PDF", glyph: <path d="M7 17c3-1 4-5 3-8-.5 3 2 6 6 7-3-.5-6 .5-9 1Z" /> },
  json: { color: "#B7791F", label: "JSON", glyph: <path d="M10 9c-1.5 0-2 .8-2 2v1c0 .8-.5 1-1 1 .5 0 1 .2 1 1v1c0 1.2.5 2 2 2M14 9c1.5 0 2 .8 2 2v1c0 .8.5 1 1 1-.5 0-1 .2-1 1v1c0 1.2-.5 2-2 2" /> },
  markdown: { color: "#365033", label: "MD", glyph: <path d="M7 17v-7l2.5 3L12 10v7M15 10v6m-2-2 2 2 2-2" /> },
  text: { color: "#5B6670", label: "TXT", glyph: <path d="M7 10h10M7 13h10M7 16h6" /> },
  word: { color: "#2B579A", label: "DOC", glyph: <path d="M7 10h10M7 13h10M7 16h6" /> },
  slides: { color: "#C55A11", label: "PPT", glyph: <path d="M7 10h10v6H7zM12 16v2" /> },
  archive: { color: "#7A5C2E", label: "ZIP", glyph: <path d="M12 9v2m0 2v2m0 2v1M10.5 11h3M10.5 15h3" /> },
  image: { color: "#8E44AD", label: "IMG", glyph: <path d="M7 17l3-4 2 2 2-3 3 5ZM9 10.5h.01" /> },
  audio: { color: "#117A8B", label: "AUDIO", glyph: <path d="M9 15V9l7-1v6M9 15a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm7-1a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z" /> },
  other: { color: "#5B6670", label: "FILE", glyph: <path d="M7 10h10M7 13h10" /> },
};

const extensionKind: Record<string, FileKind> = {
  xlsx: "sheet", xls: "sheet", xlsm: "sheet", ods: "sheet",
  csv: "csv", tsv: "csv",
  pdf: "pdf",
  json: "json", jsonl: "json",
  md: "markdown", markdown: "markdown",
  txt: "text", log: "text",
  doc: "word", docx: "word", odt: "word", rtf: "word",
  ppt: "slides", pptx: "slides", odp: "slides",
  zip: "archive", rar: "archive", "7z": "archive", gz: "archive", tar: "archive",
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", svg: "image",
  mp3: "audio", wav: "audio", ogg: "audio", m4a: "audio",
};

export function fileExtension(name: string, fallback = ""): string {
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 && dot < name.length - 1 ? name.slice(dot + 1) : fallback;
  return ext.toLowerCase();
}

export default function FileTypeIcon({ name, format = "", size = 40 }: { name: string; format?: string; size?: number }) {
  const ext = fileExtension(name, format);
  const style = kinds[extensionKind[ext] ?? "other"];
  const label = (extensionKind[ext] ? ext : style.label).slice(0, 4).toUpperCase();
  return <svg aria-hidden="true" viewBox="0 0 24 28" width={size} height={size * 28 / 24} fill="none" stroke={style.color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" className="shrink-0" data-file-kind={ext || "other"}>
    <path d="M4 1.5h11l5 5v20H4z" fill="#fff" />
    <path d="M15 1.5v5h5" />
    <g transform="translate(0 -1)">{style.glyph}</g>
    <rect x="2" y="19.5" width="14" height="6" fill={style.color} stroke="none" />
    <text x="9" y="24.2" textAnchor="middle" fontSize="4.6" fontWeight="700" fill="#fff" stroke="none" fontFamily="sans-serif">{label}</text>
  </svg>;
}
