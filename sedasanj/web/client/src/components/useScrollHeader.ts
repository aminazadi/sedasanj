import { useEffect, useRef, useState } from "react";
import { nextHeaderScroll } from "../lib/headerScroll.mjs";

export function useScrollHeader(menuOpen: boolean) {
  const headerRef = useRef<HTMLElement>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let state = { y: Math.max(0, window.scrollY), anchor: Math.max(0, window.scrollY), direction: 0, hidden: false };
    setHidden(false);
    const onScroll = () => {
      state = nextHeaderScroll(state, window.scrollY);
      setHidden(!menuOpen && !headerRef.current?.contains(document.activeElement) && state.hidden);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [menuOpen]);

  return { headerRef, hidden };
}
