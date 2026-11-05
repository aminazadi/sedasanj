export const DOCUMENT_ACTION_CLASS = "flex h-9 w-9 shrink-0 items-center justify-center border border-[#898989] bg-white text-[#000000] transition hover:bg-[#B2AC88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-40";
const paths = {
  back: "m9 18 6-6-6-6",
  audio: "M5 9v6h4l5 4V5L9 9H5Z M18 9a4 4 0 0 1 0 6 M20.5 6.5a8 8 0 0 1 0 11",
  download: "M12 3v12 m-5-5 5 5 5-5 M5 16v5h14v-5",
  print: "M7 8V3h10v5 M7 17H3V8h18v9h-4 M7 14h10v7H7Z M17 11h1",
  share: "M12 16V3 m-5 5 5-5 5 5 M5 13v8h14v-8",
};
export default function DocumentActionIcon({ name, busy = false }: { name: keyof typeof paths; busy?: boolean }) {
  return <svg className={`h-5 w-5${busy ? " animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
    {busy ? <path d="M12 3a9 9 0 1 1-9 9" /> : <path d={paths[name]} />}
  </svg>;
}
