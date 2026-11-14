import { useEffect, useState } from "react";
import fallback from "../assets/article-default.webp";

/** Keep article cards illustrated when no cover is set or the selected file fails. */
export default function ArticleThumbnail({ src }: { src?: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const isFallback = !src || failed;
  return <img
    className={`article-thumbnail${isFallback ? " article-thumbnail-fallback" : ""}`}
    src={isFallback ? fallback : src}
    alt=""
    loading="lazy"
    width={640}
    height={360}
    onError={isFallback ? undefined : () => setFailed(true)}
  />;
}
